"""Query engine - 5-stage pipeline for reading from MCS.

The 5 stages, in order, per openspec/specs/query-pipeline/spec.md:

    ① 前置插件链      (PostprocessPlugin chain, optional)
    ② 种子定位        (EntryPlugin chain + TrimPlugin)
    ③ 语义理解 Loop   (BFS + visited + max_rounds + max_picked)
    ④ 仲裁            (ArbitrationPlugin, ≤1)
    ⑤ 后置处理链      (PostprocessPlugin chain)

Default return value is ``List[Node]`` (the ``result_set`` field of
``QueryContext``). Synthesis to a natural-language string is OPTIONAL,
provided by a postprocess plugin in stage ⑤.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mcs.core.graph import GraphStore, Node
    from mcs.core.plugin_manager import PluginManager
    from mcs.core.token_budget import TokenBudget
    from mcs.interfaces.llm import LLMInterface


@dataclass
class QueryContext:
    """State threaded through one query() call.

    The 4 lifecycle fields per spec:

    - ``system_prompt``: user-configured (domain + role), invariant
    - ``user_input``: the original query string, invariant
    - ``intermediate``: ``accumulated`` during stage ③ Loop
    - ``result_set``: the final selected node set after stage ④

    See openspec/specs/query-pipeline/spec.md "QueryContext 含四个状态字段".
    """

    system_prompt: str = ""
    user_input: str = ""
    intermediate: list[Node] = field(default_factory=list)
    result_set: list[Node] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)


class QueryEngine:
    """Read pipeline orchestrator.

    Wires together: graph + llm + plugin chains + token budget. Plugin
    chains are read out of ``plugin_manager`` at call time, so dynamic
    plugin (un)registration is supported between calls.
    """

    def __init__(
        self,
        graph: GraphStore,
        llm: LLMInterface,
        plugin_manager: PluginManager,
        token_budget: TokenBudget,
        max_rounds: int = 5,
        max_picked: int = 50,
        system_prompt: str = "",
    ):
        self.graph = graph
        self.llm = llm
        self.plugin_manager = plugin_manager
        self.token_budget = token_budget
        self.max_rounds = max_rounds
        self.max_picked = max_picked
        self.system_prompt = system_prompt

    # === Public API ===

    def query(
        self,
        text: str,
        existing_context: list[Node] | None = None,
    ) -> Any:
        """Execute the 5-stage read pipeline.

        Returns the output of the last postprocess plugin, or the
        ``result_set`` (List[Node]) if no postprocess plugin transforms
        the type.
        """
        ctx = QueryContext(
            system_prompt=self.system_prompt,
            user_input=text,
        )

        # Stage ①: 前置插件链 (optional; applies to query text)
        processed_text = self._run_preprocess(text, ctx)

        # Stage ②: 种子定位 (skipped if existing_context provided)
        if existing_context is not None:
            seeds = list(existing_context)
        else:
            seeds = self._locate_seeds(processed_text, ctx)

        # Stage ③: 语义理解 Loop
        ctx.intermediate = self._traverse(seeds, processed_text, ctx)

        # Stage ④: 仲裁
        ctx.result_set = self._arbitrate(ctx.intermediate, processed_text, ctx)

        # Stage ⑤: 后置处理链
        return self._run_postprocess(ctx.result_set, ctx)

    # === Stage helpers ===

    def _run_preprocess(self, text: str, ctx: QueryContext) -> str:
        """Stage ①: serial PostprocessPlugin chain treating text as input.

        Note: read-pipeline preprocess plugins receive a string and return
        a (possibly transformed) string. Plugins that don't modify the
        text should return it unchanged.
        """
        from mcs.interfaces.postprocess_plugin import PostprocessPluginInterface

        plugins = self._read_chain_for_position("query_preprocess")
        if not plugins:
            # No registered preprocess plugins; the query string passes through.
            del PostprocessPluginInterface  # silence unused-import lint in TYPE_CHECKING-less paths
            return text
        result: Any = text
        for plugin in plugins:
            result = plugin.process(result, ctx)
        return result if isinstance(result, str) else text

    def _locate_seeds(self, query: str, ctx: QueryContext) -> list[Node]:
        """Stage ②: run all EntryPlugins (priority-sorted), merge, trim."""
        from mcs.interfaces.entry_plugin import EntryPluginInterface
        from mcs.interfaces.trim_plugin import TrimPluginInterface

        entry_plugins = self.plugin_manager.get_all(EntryPluginInterface)
        accumulated: list[Node] = []
        seen: set[str] = set()
        exclusive_hit = False

        for plugin in entry_plugins:
            if exclusive_hit and not plugin.exclusive:
                # A higher-priority exclusive plugin already won; skip lower-priority.
                continue
            candidates = plugin.locate(query, ctx) or []
            if not candidates:
                continue
            for node in candidates:
                if node.id not in seen:
                    seen.add(node.id)
                    accumulated.append(node)
            if plugin.exclusive:
                exclusive_hit = True

        # Trim if over budget
        trim = self.plugin_manager.get(TrimPluginInterface)
        if trim is not None and accumulated:
            try:
                accumulated = trim.trim(accumulated, self.token_budget.T)
            except NotImplementedError:
                # Budget check not yet implemented; pass through unchanged.
                pass
        return accumulated

    def _traverse(
        self,
        seeds: list[Node],
        query: str,
        ctx: QueryContext,
    ) -> list[Node]:
        """Stage ③: BFS with visited set + max_rounds + max_picked."""
        if not seeds:
            return []

        visited: set[str] = set()
        accumulated: list[Node] = list(seeds)
        for node in seeds:
            visited.add(node.id)
        frontier: list[Node] = list(seeds)

        for _round in range(self.max_rounds):
            if not frontier:
                break
            if len(accumulated) >= self.max_picked:
                break

            next_frontier: list[Node] = []
            for node in frontier:
                if len(accumulated) >= self.max_picked:
                    break

                neighbors = self.graph.get_neighbors(node.id) or []
                if not neighbors:
                    continue

                # LLM call: which neighbors lead toward the query target?
                selected_ids = self.llm.call(
                    purpose="decide_directions",
                    nodes_in=[node, *neighbors],
                    free_args={
                        "query": query,
                        "accumulated": _summarize_for_prompt(accumulated),
                    },
                ) or []
                selected_set = set(selected_ids)
                for neighbor in neighbors:
                    if neighbor.id in selected_set and neighbor.id not in visited:
                        visited.add(neighbor.id)
                        accumulated.append(neighbor)
                        next_frontier.append(neighbor)
                        if len(accumulated) >= self.max_picked:
                            break

            frontier = next_frontier

        return accumulated

    def _arbitrate(
        self,
        accumulated: list[Node],
        query: str,
        ctx: QueryContext,
    ) -> list[Node]:
        """Stage ④: ≤1 ArbitrationPlugin; default is pass-through."""
        from mcs.interfaces.arbitration_plugin import ArbitrationPluginInterface

        plugin = self.plugin_manager.get(ArbitrationPluginInterface)
        if plugin is None:
            return list(accumulated)
        result = plugin.arbitrate(accumulated, query, ctx)
        if not isinstance(result, list):
            raise TypeError(
                f"Arbitration plugin {plugin.name!r} returned non-list "
                f"({type(result).__name__}); arbitration must return List[Node]"
            )
        return result

    def _run_postprocess(self, selected: list[Node], ctx: QueryContext) -> Any:
        """Stage ⑤: serial PostprocessPlugin chain for query position."""
        plugins = self._read_chain_for_position("query_postprocess")
        if not plugins:
            return selected
        result: Any = selected
        for plugin in plugins:
            result = plugin.process(result, ctx)
        return result

    def _read_chain_for_position(self, position: str) -> list:
        """Resolve which PostprocessPlugins are mounted at ``position``.

        Phase 1 convention: a plugin attribute ``position`` (str) selects
        the mount point ("query_preprocess", "query_postprocess",
        "write_preprocess"). Plugins without the attribute default to
        "query_postprocess".
        """
        from mcs.interfaces.postprocess_plugin import PostprocessPluginInterface

        plugins = self.plugin_manager.get_all(PostprocessPluginInterface)
        return [p for p in plugins if getattr(p, "position", "query_postprocess") == position]


def _summarize_for_prompt(nodes: list[Node]) -> str:
    """Compact one-line-per-node summary for accumulated context in
    ``decide_directions`` calls. Avoids dragging full content through
    repeated prompts.
    """
    from mcs.core.context_renderer import ContextRenderer

    lines = []
    for node in nodes:
        summary = ContextRenderer.get_summary(node)
        lines.append(f"- {node.name} (id={node.id}): {summary}")
    return "\n".join(lines) if lines else "(无)"

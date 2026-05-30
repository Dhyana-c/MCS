"""Write pipeline - 6-stage pipeline for ingesting text into MCS.

The 6 stages, in order, per openspec/specs/write-pipeline/spec.md:

    ① 前置插件链         (PostprocessPlugin chain on text)
    ② 关联节点定位       (reuse query pipeline)
    ③ 概念提取           (LLM: extract_concepts)
    ④ 关系判定           (LLM: judge_relations → DecisionList)
    ⑤ 图更新             (no LLM; apply DecisionList atomically)
    ⑥ 压缩判定插件链     (CompactionPlugin chain, conditional)

Stage ④ produces a ``DecisionList`` (pure data); stage ⑤ applies it.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from mcs.core.decisions import ConceptDraft, Decision, DecisionList
from mcs.core.errors import UnknownActionError

if TYPE_CHECKING:
    from mcs.core.graph import GraphStore, Node
    from mcs.core.plugin_manager import PluginManager
    from mcs.core.query_engine import QueryEngine
    from mcs.core.token_budget import TokenBudget
    from mcs.interfaces.llm import LLMInterface


@dataclass
class WriteContext:
    """State threaded through one ingest() call.

    The 7 lifecycle fields per spec, plus free metadata:

    - ``system_prompt``: invariant
    - ``user_input``: original text, invariant
    - ``processed``: output of stage ① preprocess
    - ``related``: output of stage ② (from reused query pipeline)
    - ``concepts``: output of stage ③
    - ``decisions``: output of stage ④
    - ``changed``: output of stage ⑤ (nodes newly created or merged)

    See openspec/specs/write-pipeline/spec.md "WriteContext 含七个状态字段".
    """

    system_prompt: str = ""
    user_input: str = ""
    processed: str = ""
    related: list[Node] = field(default_factory=list)
    concepts: list[ConceptDraft] = field(default_factory=list)
    decisions: DecisionList = field(default_factory=list)
    changed: list[Node] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)
    skip: bool = False


class WritePipeline:
    """Write pipeline orchestrator.

    Holds references to:
      - graph (for stage ⑤ updates)
      - llm   (for stage ③ ④ LLM calls; also for ⑥ compaction's llm_caller)
      - query_engine (for stage ② reuse)
      - plugin_manager (to resolve preprocess and compaction chains)
    """

    def __init__(
        self,
        graph: GraphStore,
        llm: LLMInterface,
        query_engine: QueryEngine,
        plugin_manager: PluginManager,
        token_budget: TokenBudget,
        system_prompt: str = "",
    ):
        self.graph = graph
        self.llm = llm
        self.query_engine = query_engine
        self.plugin_manager = plugin_manager
        self.token_budget = token_budget
        self.system_prompt = system_prompt

    # === Public API ===

    def ingest(self, text: str, **metadata: Any) -> WriteContext:
        """Execute the 6-stage write pipeline. Returns the final WriteContext.

        Empty concept extraction silently returns (stages ④⑤⑥ skipped);
        idempotency-skip via ``ctx.skip = True`` also short-circuits.
        """
        ctx = WriteContext(
            system_prompt=self.system_prompt,
            user_input=text,
            metadata=dict(metadata),
        )

        # Stage ①: 前置插件链 (idempotency / summarization / etc.)
        processed = self._run_preprocess(text, ctx)
        if ctx.skip:
            return ctx
        ctx.processed = processed

        # Stage ②: 关联节点定位 (reuse query pipeline)
        related = self.query_engine.query(processed)
        ctx.related = related if isinstance(related, list) else []

        # Stage ③: 概念提取
        concepts = self.llm.call(
            purpose="extract_concepts",
            nodes_in=ctx.related,
            free_args={"text": processed},
        ) or []
        ctx.concepts = concepts
        if not concepts:
            return ctx  # silent return on 0 concepts

        # Stage ④: 关系判定
        decisions = self.llm.call(
            purpose="judge_relations",
            nodes_in=ctx.related,
            free_args={"concepts": _format_concepts(concepts)},
        ) or []
        # Re-attach the full ConceptDraft objects (parser only knew names)
        _reattach_concepts(decisions, concepts)
        ctx.decisions = decisions

        # Stage ⑤: 图更新
        ctx.changed = self._apply_decisions(decisions)
        self._notify_indexes(ctx.changed)

        # Stage ⑥: 压缩判定插件链
        self._run_compaction(ctx.changed)

        return ctx

    def _notify_indexes(self, changed_nodes: list[Node]) -> None:
        """Tell each IndexInterface plugin about changed nodes so the index
        stays in sync. Replaces the role of the old ``on_created_or_merged``
        pipeline hook.
        """
        from mcs.interfaces.index import IndexInterface

        indexes = self.plugin_manager.get_all(IndexInterface)
        for index in indexes:
            for node in changed_nodes:
                try:
                    index.update_entry(node)
                except NotImplementedError:
                    continue

    # === Stage helpers ===

    def _run_preprocess(self, text: str, ctx: WriteContext) -> str:
        """Stage ①: serial PostprocessPlugin chain with ``position == 'write_preprocess'``."""
        from mcs.interfaces.postprocess_plugin import PostprocessPluginInterface

        plugins = [
            p
            for p in self.plugin_manager.get_all(PostprocessPluginInterface)
            if getattr(p, "position", "query_postprocess") == "write_preprocess"
        ]
        result: Any = text
        for plugin in plugins:
            result = plugin.process(result, ctx)
            if ctx.skip:
                return result if isinstance(result, str) else text
        return result if isinstance(result, str) else text

    def _apply_decisions(self, decisions: DecisionList) -> list[Node]:
        """Stage ⑤: dispatch each Decision to atomic GraphStore operations.

        Returns the list of nodes that were newly created OR merged
        (i.e. nodes whose state changed).
        """

        changed: list[Node] = []
        for decision in decisions:
            action = decision.action
            if action == "merge":
                if decision.target_id is None:
                    raise UnknownActionError("merge without target_id")
                self._dispatch_merge(decision)
                node = self.graph.get_node(decision.target_id)
                if node is not None:
                    changed.append(node)
            elif action == "create":
                node = self._dispatch_create(decision)
                changed.append(node)
            elif action == "attach_statement":
                if decision.target_id is None:
                    raise UnknownActionError("attach_statement without target_id")
                self._dispatch_attach(decision)
                node = self.graph.get_node(decision.target_id)
                if node is not None:
                    changed.append(node)
            elif action == "no_op":
                continue  # explicit non-action; nothing to do
            else:
                raise UnknownActionError(action)
        return changed

    def _dispatch_merge(self, decision: Decision) -> None:
        """Merge: fold the new concept (name + aliases) into ``target_id``.

        Updates the alias slot of the target via ``GraphStore.update_node``.
        """
        updates: dict[str, Any] = {}
        if decision.aliases_to_add:
            updates["_extension_alias_add"] = decision.aliases_to_add
        if decision.concept and decision.concept.name:
            updates["_extension_alias_add"] = (
                updates.get("_extension_alias_add", [])
                + [decision.concept.name]
            )
        # Initial statements (if any) attach to the target as separate edges/notes.
        if decision.initial_statements:
            updates["_pending_statements"] = decision.initial_statements
        self.graph.update_node(decision.target_id, updates)  # type: ignore[arg-type]

    def _dispatch_create(self, decision: Decision) -> Node:
        """Create: new node + edges to each anchor in ``edges_to``."""
        from mcs.core.graph import Node

        c = decision.concept
        if c is None:
            raise UnknownActionError("create without concept payload")
        node = Node(
            id=str(uuid.uuid4()),
            name=c.name,
            content=c.content,
            role="concept",
        )
        self.graph.add_node(node)
        for anchor_id in decision.edges_to or []:
            self.graph.add_edge(node.id, anchor_id)
        # Initial statements become attached statements on the new node.
        if decision.initial_statements:
            # Phase 1 keeps statements in extensions; Phase 2 wraps as property nodes.
            node.extensions.setdefault("statements", {"items": []})["items"].extend(
                decision.initial_statements
            )
        return node

    def _dispatch_attach(self, decision: Decision) -> None:
        """Attach a statement to an attribute node (Phase 1 simple list)."""
        if not decision.statement:
            return
        node = self.graph.get_node(decision.target_id)  # type: ignore[arg-type]
        if node is None:
            return
        slot = node.extensions.setdefault("statements", {"items": []})
        slot.setdefault("items", []).append(decision.statement)

    def _run_compaction(self, changed_nodes: list[Node]) -> None:
        """Stage ⑥: each CompactionPlugin checks should_run, then run."""
        from mcs.interfaces.compaction_plugin import CompactionPluginInterface

        plugins = self.plugin_manager.get_all(CompactionPluginInterface)
        for plugin in plugins:
            if plugin.should_run(changed_nodes, self.graph):
                plugin.run(changed_nodes, self.graph, self.llm.call)


# === Helpers ===


def _format_concepts(concepts: list[ConceptDraft]) -> str:
    """Compact string representation of ConceptDrafts for the
    ``judge_relations`` LLM prompt's ``{concepts}`` placeholder.
    """
    lines = []
    for i, c in enumerate(concepts, 1):
        lines.append(f"{i}. {c.name}: {c.content}")
        for hint in c.relation_hints:
            lines.append(f"   - {hint}")
    return "\n".join(lines) if lines else "(无)"


def _reattach_concepts(
    decisions: DecisionList, concepts: list[ConceptDraft]
) -> None:
    """The judge_relations parser only carries concept_name; this helper
    swaps in the full ConceptDraft object from the extract_concepts output.
    """
    by_name = {c.name: c for c in concepts}
    for d in decisions:
        if d.concept is not None and d.concept.name in by_name:
            d.concept = by_name[d.concept.name]

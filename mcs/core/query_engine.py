"""查询引擎 - 从 MCS 读取的 5 阶段管道。

5 个阶段按顺序执行，参见 openspec/specs/query-pipeline/spec.md：

    ① 前置插件链      (PostprocessPlugin chain, 可选)
    ② 种子定位        (EntryPlugin chain + TrimPlugin)
    ③ 语义理解 Loop   (BFS + visited + max_rounds + max_picked)
    ④ 仲裁            (ArbitrationPlugin, ≤1)
    ⑤ 后置处理链      (PostprocessPlugin chain)

默认返回值为 ``List[Node]``（``QueryContext`` 的 ``result_set`` 字段）。
合成为自然语言字符串是可选的，由阶段 ⑤ 中的后处理插件提供。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mcs.core.graph import Node
    from mcs.core.plugin_manager import PluginManager
    from mcs.core.store import StoreInterface
    from mcs.core.token_budget import TokenBudget
    from mcs.interfaces.llm import LLMInterface

logger = logging.getLogger(__name__)


@dataclass
class QueryContext:
    """贯穿一次 query() 调用的状态。

    规范中的 4 个生命周期字段：

    - ``system_prompt``: 用户配置的（领域 + 角色），不变量
    - ``user_input``: 原始查询字符串，不变量
    - ``intermediate``: 在阶段 ③ Loop 中 ``accumulated``
    - ``result_set``: 阶段 ④ 后的最终选定节点集

    参见 openspec/specs/query-pipeline/spec.md "QueryContext 含四个状态字段"。
    """

    system_prompt: str = ""
    user_input: str = ""
    intermediate: list[Node] = field(default_factory=list)
    result_set: list[Node] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)


class QueryEngine:
    """读取管道协调器。

    组合：graph + llm + 插件链 + token 预算。插件链在调用时从 ``plugin_manager``
    读取，因此支持在调用之间动态（取消）注册插件。
    """

    def __init__(
            self,
            store: StoreInterface,
            llm: LLMInterface,
            plugin_manager: PluginManager,
            token_budget: TokenBudget,
            max_rounds: int = 5,
            max_picked: int = 50,
            system_prompt: str = "",
            seed_bounding: bool = False,
    ):
        self.store = store
        self.llm = llm
        self.plugin_manager = plugin_manager
        self.token_budget = token_budget
        self.max_rounds = max_rounds
        self.max_picked = max_picked
        self.system_prompt = system_prompt
        self.seed_bounding = seed_bounding

    # === 公共 API ===

    def query(
            self,
            text: str,
            existing_context: list[Node] | None = None,
    ) -> Any:
        """执行 5 阶段读取管道。

        返回最后一个后处理插件的输出，如果没有后处理插件转换类型，
        则返回 ``result_set`` (List[Node])。
        """
        ctx = QueryContext(
            system_prompt=self.system_prompt,
            user_input=text,
        )

        # 阶段 ①: 前置插件链（可选；应用于查询文本）
        processed_text = self._run_preprocess(text, ctx)

        # 阶段 ②: 种子定位（如果提供了 existing_context 则跳过）
        if existing_context is not None:
            seeds = list(existing_context)
        else:
            seeds = self._locate_seeds(processed_text, ctx)

        # 阶段 ②.5（opt-in）：种子集超容量时归纳成分层种子图（虚拟根 + fanout reduce）
        if self.seed_bounding:
            seeds = self._bound_seed_graph(seeds, ctx)

        # 阶段 ③: 语义理解 Loop
        ctx.intermediate = self._traverse(seeds, processed_text, ctx)

        # 阶段 ④: 仲裁
        ctx.result_set = self._arbitrate(ctx.intermediate, processed_text, ctx)

        # 阶段 ⑤: 后置处理链
        return self._run_postprocess(ctx.result_set, ctx)

    # === 阶段辅助方法 ===

    def _run_preprocess(self, text: str, ctx: QueryContext) -> str:
        """阶段 ①：将文本作为输入的串行 PreprocessPlugin 链。

        注意：读取管道预处理插件接收字符串并返回（可能转换的）字符串。
        不修改文本的插件应返回未更改的文本。
        """
        from mcs.core.plugin import PluginType

        plugins = self.plugin_manager.get_all(PluginType.PREPROCESS)
        if not plugins:
            return text
        result: Any = text
        for plugin in plugins:
            result = plugin.preprocess(result, ctx)
        return result if isinstance(result, str) else text

    def _locate_seeds(self, query: str, ctx: QueryContext) -> list[Node]:
        """阶段 ②：运行所有 EntryPlugins（按优先级排序），合并，裁剪。"""
        from mcs.core.plugin import PluginType

        entry_plugins = self.plugin_manager.get_all(PluginType.ENTRY)
        accumulated: list[Node] = []
        seen: set[str] = set()
        exclusive_hit = False

        for plugin in entry_plugins:
            if exclusive_hit and not plugin.exclusive:
                # 更高优先级的独占插件已获胜；跳过低优先级插件
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

        # 如果超出预算则裁剪
        trim = self.plugin_manager.get(PluginType.TRIM)
        if trim is not None and accumulated:
            try:
                accumulated = trim.trim(accumulated, self.token_budget.T)
            except NotImplementedError:
                # 预算检查尚未实现；原样传递
                pass
        return accumulated

    def _bound_seed_graph(
            self, seeds: list[Node], ctx: QueryContext
    ) -> list[Node]:
        """种子集超容量时做分层收敛。

        策略：
        1. 若存在持久虚拟根 __seed_root__ 且有 LLM，从中导航定位最相关 hub
        2. 否则，按预算截断（保守兜底）

        与 hub_fallback 协同：hub_fallback 已从 root 导航，
        本方法仅在 hub_fallback 返回过多种子时做二次收敛。

        估算口径与渲染口径一致：使用 estimate_node（含格式行、body、extensions）。
        """
        if not seeds:
            return seeds
        tb = self.token_budget
        if tb is None:
            return seeds

        # 检查是否超出预算
        used = sum(tb.estimate_node(n) for n in seeds)
        if used <= tb.T:
            return seeds  # 未超预算，直接返回

        # 超预算：尝试从 root 导航收敛
        from mcs.plugins.phase1.fanout_reducer import SEED_ROOT_ID
        root = self.store.get_node(SEED_ROOT_ID)

        if root is not None and self.llm is not None:
            try:
                narrowed = self._navigate_to_relevant_hubs(seeds, root, ctx)
                if narrowed:
                    # 再次检查预算
                    narrowed_used = sum(tb.estimate_node(n) for n in narrowed)
                    if narrowed_used <= tb.T:
                        return narrowed
            except Exception:
                logger.warning("导航收敛失败，回退截断")

        # 兜底：按优先级截断
        kept: list[Node] = []
        used = 0
        for n in seeds:
            used += tb.estimate_node(n)
            if used > tb.T and kept:
                break
            kept.append(n)
        return kept

    def _navigate_to_relevant_hubs(
            self, seeds: list[Node], root: Node, ctx: QueryContext
    ) -> list[Node]:
        """从 root 导航到最相关的 hub 子集。

        输入：超量的种子集
        输出：预算内的相关 hub 子集
        """
        # 获取 root 的直接子节点（顶层 hub）
        top_hubs = self.store.get_out_neighbors(root.id)
        if not top_hubs:
            return seeds

        # LLM 导航：选择最相关的顶层 hub
        selected_ids = self.llm.call(
            purpose="navigate_hub",
            nodes_in=[root, *top_hubs],
            free_args={"target": ctx.user_input},
        ) or []

        selected = [self.store.get_node(i) for i in selected_ids]
        selected = [n for n in selected if n is not None]

        # 从选中的 hub 继续下钻
        result: list[Node] = []
        visited: set[str] = {root.id}

        for hub in selected:
            if hub.id in visited:
                continue
            visited.add(hub.id)

            # 获取 hub 的概念成员
            members = self.store.get_out_neighbors(hub.id)
            for m in members:
                if m.id in visited or m.role == "hub":
                    continue
                result.append(m)

        return result[: self.max_picked]

    def _traverse(
            self,
            seeds: list[Node],
            query: str,
            ctx: QueryContext,
    ) -> list[Node]:
        """阶段 ③：BFS 遍历，带 visited 集合 + max_rounds + max_picked。"""
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

                neighbors = self.store.get_neighbors(node.id) or []
                if not neighbors:
                    continue

                # LLM 调用：哪些邻居指向查询目标？
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
        """阶段 ④：≤1 个 ArbitrationPlugin；默认为直通。"""
        from mcs.core.plugin import PluginType

        plugin = self.plugin_manager.get(PluginType.ARBITRATION)
        if plugin is None:
            return list(accumulated)
        result = plugin.arbitrate(accumulated, query, ctx)
        if not isinstance(result, list):
            raise TypeError(
                f"Arbitration plugin {plugin.get_name()!r} returned non-list "
                f"({type(result).__name__}); arbitration must return List[Node]"
            )
        return result

    def _run_postprocess(self, selected: list[Node], ctx: QueryContext) -> Any:
        """阶段 ⑤：针对查询位置的串行 PostprocessPlugin 链。"""
        from mcs.core.plugin import PluginType

        plugins = self.plugin_manager.get_all(PluginType.POSTPROCESS)
        if not plugins:
            return selected
        result: Any = selected
        for plugin in plugins:
            result = plugin.process(result, ctx)
        return result


def _summarize_for_prompt(nodes: list[Node]) -> str:
    """用于 ``decide_directions`` 调用中累积上下文的紧凑单行每节点摘要。
    避免在重复提示中拖拽完整内容。
    """
    from mcs.core.context_renderer import ContextRenderer

    lines = []
    for node in nodes:
        summary = ContextRenderer.get_summary(node)
        lines.append(f"- {node.name} (id={node.id}): {summary}")
    return "\n".join(lines) if lines else "(无)"

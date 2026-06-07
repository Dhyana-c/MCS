"""查询引擎 - 从 MCS 读取的 5 阶段管道。

5 个阶段按顺序执行，参见 openspec/specs/query-pipeline/spec.md：

    ① 前置插件链      (PostprocessPlugin chain, 可选)
    ② 种子定位        (EntryPlugin chain + TrimPlugin)
    ③ 语义理解 Loop   (BFS + visited + max_rounds + token_budget)
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
            max_accumulated_nodes: int = 1000,
            system_prompt: str = "",
    ):
        self.store = store
        self.llm = llm
        self.plugin_manager = plugin_manager
        self.token_budget = token_budget
        self.max_rounds = max_rounds
        self.max_accumulated_nodes = max_accumulated_nodes
        self.system_prompt = system_prompt

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
        """阶段 ②：运行所有 EntryPlugins（按优先级排序），合并，裁剪，语义筛选。

        执行顺序：EntryPlugin 链（合并）→ TrimPlugin（硬截断）→ SeedSelectorPlugin 链（语义筛选）
        """
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

        # SeedSelectorPlugin 链：语义筛选
        selector_plugins = self.plugin_manager.get_all(PluginType.SEED_SELECTOR)
        if selector_plugins and accumulated:
            for selector in selector_plugins:
                try:
                    accumulated = selector.select(
                        seeds=accumulated,
                        query=query,
                        budget=self.token_budget.T,
                        ctx=ctx,
                    )
                except Exception:
                    logger.warning(
                        "SeedSelectorPlugin %s 执行失败，跳过",
                        selector.get_name(),
                        exc_info=True,
                    )

        return accumulated

    def _traverse(
            self,
            seeds: list[Node],
            query: str,
            ctx: QueryContext,
    ) -> list[Node]:
        """阶段 ③：token 预算驱动的 BFS 遍历。

        种子已在阶段 ② 经过 SeedSelectorPlugin 筛选，直接加入 accumulated。
        每轮：获取 accumulated 中节点的邻居作为 frontier → LLM 筛选 → 选中的加入 accumulated。

        核心不变量保证：frontier + accumulated + query + system_prompt ≤ 窗口
        """
        if not seeds:
            return []

        visited: set[str] = set()
        accumulated: list[Node] = list(seeds)
        for node in seeds:
            visited.add(node.id)
        budget = self.token_budget.T

        for _round in range(self.max_rounds):
            # 检查 token 预算
            used_tokens = sum(
                self.token_budget.estimate_node(n) for n in accumulated
            )
            if used_tokens >= budget:
                logger.info(
                    "accumulated token=%d >= budget=%d, 终止",
                    used_tokens, budget,
                )
                break

            # 安全阀：节点数硬上限
            if len(accumulated) >= self.max_accumulated_nodes:
                logger.info(
                    "遍历达到 max_accumulated_nodes=%d, 终止",
                    self.max_accumulated_nodes,
                )
                break

            # 获取 accumulated 中节点的未访问邻居作为 frontier
            frontier: list[Node] = []
            for node in accumulated:
                neighbors = self.store.get_neighbors(node.id) or []
                for neighbor in neighbors:
                    if neighbor.id not in visited:
                        frontier.append(neighbor)
                        visited.add(neighbor.id)  # 先标记，防止重复加入

            if not frontier:
                break

            # LLM 筛选 frontier：一次性调用
            selected_ids = self.llm.call(
                purpose="select_nodes",
                nodes_in=frontier,
                free_args={
                    "query": query,
                    "accumulated_summary": _summarize_for_prompt(accumulated),
                },
            ) or []
            selected_set = set(selected_ids)

            if not selected_set:
                logger.debug("LLM 未选中任何节点，遍历终止")
                break

            # 将选中的节点加入 accumulated
            for node in frontier:
                if node.id in selected_set:
                    accumulated.append(node)
                    if len(accumulated) >= self.max_accumulated_nodes:
                        break

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

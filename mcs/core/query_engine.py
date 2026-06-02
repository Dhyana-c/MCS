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

import uuid
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mcs.core.graph import GraphStore, Node
    from mcs.core.plugin_manager import PluginManager
    from mcs.core.token_budget import TokenBudget
    from mcs.interfaces.llm import LLMInterface


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
        graph: GraphStore,
        llm: LLMInterface,
        plugin_manager: PluginManager,
        token_budget: TokenBudget,
        max_rounds: int = 5,
        max_picked: int = 50,
        system_prompt: str = "",
        seed_bounding: bool = False,
    ):
        self.graph = graph
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
        """阶段 ①：将文本作为输入的串行 PostprocessPlugin 链。

        注意：读取管道预处理插件接收字符串并返回（可能转换的）字符串。
        不修改文本的插件应返回未更改的文本。
        """
        plugins = self._read_chain_for_position("query_preprocess")
        if not plugins:
            return text
        result: Any = text
        for plugin in plugins:
            result = plugin.process(result, ctx)
        return result if isinstance(result, str) else text

    def _locate_seeds(self, query: str, ctx: QueryContext) -> list[Node]:
        """阶段 ②：运行所有 EntryPlugins（按优先级排序），合并，裁剪。"""
        from mcs.interfaces.entry_plugin import EntryPluginInterface
        from mcs.interfaces.trim_plugin import TrimPluginInterface

        entry_plugins = self.plugin_manager.get_all(EntryPluginInterface)
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
        trim = self.plugin_manager.get(TrimPluginInterface)
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
        """种子集超容量时，用虚拟根 + fanout reduce 归纳成分层种子图。

        复用 fanout_reducer 的图手术（design D1：查询/建图共用一套）：虚拟根临时连上
        全部种子 → 多轮 fanout reduce 把种子收敛到中间概念之下 → 返回中间概念作种子。
        中间概念落图，虚拟根用完即弃。
        """
        if not seeds:
            return seeds
        fanout = self._get_fanout_reducer()
        if fanout is None:
            return seeds
        from mcs.core.graph import Node

        root = Node(
            id=f"__seed_root__{uuid.uuid4().hex[:8]}",
            name="__seed_root__",
            content="",
            role="hub",
        )
        self.graph.add_node(root)
        for s in seeds:
            if self.graph.get_node(s.id) is not None:
                self.graph.add_edge(root.id, s.id)
        # 多轮自底向上归纳，直到虚拟根直接子集 ≤ 容量（或无进展，防死循环）
        for _ in range(self.max_rounds + 5):
            neighbors = self.graph.get_neighbors(root.id)
            if not fanout._exceeds_budget(root, neighbors):
                break
            before = len(neighbors)
            fanout.run([root], self.graph, self.llm.call)
            if len(self.graph.get_neighbors(root.id)) >= before:
                break
        new_seeds = list(self.graph.get_neighbors(root.id))
        self.graph.delete_node(root.id)  # 清理虚拟根；中间概念与成员边保留
        return new_seeds if new_seeds else seeds

    def _get_fanout_reducer(self):
        """从 plugin_manager 找 FanoutReducerPlugin（复用其图手术）。"""
        from mcs.interfaces.compaction_plugin import CompactionPluginInterface
        from mcs.plugins.phase1.fanout_reducer import FanoutReducerPlugin

        for p in self.plugin_manager.get_all(CompactionPluginInterface):
            if isinstance(p, FanoutReducerPlugin):
                return p
        return None

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

                neighbors = self.graph.get_neighbors(node.id) or []
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
        """阶段 ⑤：针对查询位置的串行 PostprocessPlugin 链。"""
        plugins = self._read_chain_for_position("query_postprocess")
        if not plugins:
            return selected
        result: Any = selected
        for plugin in plugins:
            result = plugin.process(result, ctx)
        return result

    def _read_chain_for_position(self, position: str) -> list:
        """解析哪些 PostprocessPlugins 挂载在 ``position``。

        第一阶段约定：插件属性 ``position`` (str) 选择挂载点
        ("query_preprocess", "query_postprocess", "write_preprocess")。
        没有该属性的插件默认为 "query_postprocess"。
        """
        from mcs.interfaces.postprocess_plugin import PostprocessPluginInterface

        plugins = self.plugin_manager.get_all(PostprocessPluginInterface)
        return [p for p in plugins if getattr(p, "position", "query_postprocess") == position]


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

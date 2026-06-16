"""查询引擎 - 从 MCS 读取的 5 阶段管道。

5 个阶段按顺序执行，参见 openspec/specs/query-pipeline/spec.md：

    ① 前置插件链      (PostprocessPlugin chain, 可选)
    ② 种子定位        (EntryPlugin chain + TrimPlugin)
    ③ 语义理解 Loop   (事实 BFS + visited + max_rounds + token_budget)
    ④ 仲裁            (ArbitrationPlugin, ≤1)
    ⑤ 后置处理链      (PostprocessPlugin chain)

默认返回值为 ``Subgraph``（``nodes`` + 选中事实边 ``edges``）。
后置插件 MAY 将其转换为自然语言字符串。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mcs.core.plugin_manager import PluginManager
    from mcs.core.store import StoreInterface
    from mcs.core.token_budget import TokenBudget
    from mcs.entities.graph import Edge, Node
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
    selected_edges: list[Edge] = field(default_factory=list)


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
            summary_max_nodes: int = 50,
            relation_model: str = "property_graph",
    ):
        self.store = store
        self.llm = llm
        self.plugin_manager = plugin_manager
        self.token_budget = token_budget
        self.max_rounds = max_rounds
        self.max_accumulated_nodes = max_accumulated_nodes
        self.system_prompt = system_prompt
        # 每次 select_facts 调用带的「已累积上下文」最多列多少个节点（仅 name）。
        # 旧实现带全量 name+content → 输入平方级膨胀（占查询输入 ~73%）。0 = 关闭。
        self.summary_max_nodes = summary_max_nodes
        # 关系表示模式（单一真相：builder 从 config 透传）
        self.relation_model = relation_model

    # === 公共 API ===

    def query(
            self,
            text: str,
            existing_context: list[Node] | None = None,
    ) -> Any:
        """执行 5 阶段读取管道。

        返回最后一个后处理插件的输出；如果没有后处理插件转换类型，
        则返回 ``Subgraph``（nodes + 选中事实边 edges）。
        """
        from mcs.entities.graph import Subgraph

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

        # 阶段 ③: 语义理解 Loop（事实 BFS）
        ctx.intermediate, ctx.selected_edges = self._traverse(
            seeds, processed_text, ctx
        )

        # 阶段 ④: 仲裁
        ctx.result_set = self._arbitrate(ctx.intermediate, processed_text, ctx)

        # 阶段 ⑤: 后置处理链
        # 先组装 Subgraph，再交给后置插件
        subgraph = Subgraph(
            focus_id=ctx.result_set[0].id if ctx.result_set else "",
            nodes=list(ctx.result_set),
            edges=_filter_edges_by_nodes(ctx.selected_edges, ctx.result_set),
        )
        return self._run_postprocess(subgraph, ctx)

    def query_nodes(
            self,
            text: str,
            max_rounds: int = 1,
            skip_postprocess: bool = True,
    ) -> list[Node]:
        """轻量查询模式：仅执行 ①②③ 阶段，返回 List[Node]。

        供写管线阶段②关联定位使用，跳过仲裁和后处理链。
        默认 max_rounds=1 限制遍历深度，skip_postprocess=True 跳过 ④⑤。
        """
        ctx = QueryContext(
            system_prompt=self.system_prompt,
            user_input=text,
        )

        # 阶段 ①: 前置插件链
        processed_text = self._run_preprocess(text, ctx)

        # 阶段 ②: 种子定位
        seeds = self._locate_seeds(processed_text, ctx)

        # 阶段 ③: 遍历（限制 max_rounds）
        saved_max_rounds = self.max_rounds
        try:
            self.max_rounds = max_rounds
            ctx.intermediate, _ = self._traverse(seeds, processed_text, ctx)
        finally:
            self.max_rounds = saved_max_rounds

        # 跳过 ④⑤，直接返回 result_set
        if skip_postprocess:
            return list(ctx.intermediate)

        # 阶段 ④: 仲裁
        ctx.result_set = self._arbitrate(ctx.intermediate, processed_text, ctx)

        # 阶段 ⑤: 后置处理链
        result = self._run_postprocess_nodes(ctx.result_set, ctx)
        return result if isinstance(result, list) else ctx.result_set

    # === 阶段辅助方法 ===

    def _run_preprocess(self, text: str, ctx: QueryContext) -> str:
        """阶段 ①：将文本作为输入的串行 QueryPreprocessPlugin 链。

        注意：读取管道预处理插件接收字符串并返回（可能转换的）字符串。
        不修改文本的插件应返回未更改的文本。
        """
        from mcs.core.plugin import PluginType

        plugins = self.plugin_manager.get_all(PluginType.QUERY_PREPROCESS)
        if not plugins:
            return text
        result: Any = text
        for plugin in plugins:
            result = plugin.preprocess(result, ctx)
        return result if isinstance(result, str) else text

    def _locate_seeds(self, query: str, ctx: QueryContext) -> list[Node]:
        """阶段 ②：运行所有 EntryPlugins（按优先级排序），合并，裁剪。

        执行顺序：EntryPlugin 链（合并）→ TrimPlugin 链（按优先级裁剪）
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
            try:
                candidates = plugin.locate(query, ctx) or []
            except Exception:
                logger.warning(
                    "EntryPlugin %s locate 失败，跳过",
                    plugin.get_name(),
                    exc_info=True,
                )
                continue
            if not candidates:
                continue
            for node in candidates:
                if node.id not in seen:
                    seen.add(node.id)
                    accumulated.append(node)
            if plugin.exclusive:
                exclusive_hit = True

        # TrimPlugin 链：按优先级排序依次裁剪（每个插件可做不同策略）
        trim_plugins = self.plugin_manager.get_all(PluginType.TRIM)
        if trim_plugins and accumulated:
            for trim in trim_plugins:
                try:
                    accumulated = trim.trim(
                        accumulated,
                        self.token_budget.T,
                        query=query,
                        ctx=ctx,
                    )
                except Exception:
                    logger.warning(
                        "TrimPlugin %s 执行失败，跳过",
                        trim.get_name(),
                        exc_info=True,
                    )

        return accumulated

    def _traverse(
            self,
            seeds: list[Node],
            query: str,
            ctx: QueryContext,
    ) -> tuple[list[Node], list[Edge]]:
        """阶段 ③：批量事实 BFS 遍历（分层 + 富余合并）。

        逐层扩展：每层把待扩展节点的活跃双向视图（出事实 + 入事实 + 层级邻居）
        按渲染 token 贪心打包到 ``T*0.8``——合计 ≤ 余量的多个节点合并进**一次**
        ``select_facts`` 调用（spec query-pipeline「按层分批、富余合并」）；单节点视图
        已超余量则自成一批。批量调用解析失败时**逐节点回退**，保证遍历不中断
        （spec batch-neighbor-traverse）。LLM 选中的节点 / 事实端点补入 accumulated
        并作为下一层 frontier。

        返回 (accumulated_nodes, selected_fact_edges)。
        """
        if not seeds:
            return [], []

        from mcs.core.context_renderer import ContextRenderer
        from mcs.core.errors import LLMParseError

        visited: set[str] = set()
        accumulated: list[Node] = []
        selected_edges: list[Edge] = []
        selected_edge_ids: set[str] = set()
        estimate_cache: dict[str, int] = {}
        used_tokens = 0
        budget = self.token_budget.T
        pack_budget = budget * 0.8
        renderer = ContextRenderer(self.plugin_manager)

        frontier: list[Node] = []
        for seed in seeds:
            if seed.id not in visited:
                visited.add(seed.id)
                accumulated.append(seed)
                used_tokens += self.token_budget.estimate_node(
                    seed, estimate_cache
                )
                frontier.append(seed)

        def _node_view(node: Node):
            """单节点活跃双向视图 (view_nodes, relation_edges)；无可扩展内容返回 (None, None)。"""
            children = self.store.get_out_hierarchy(node.id) or []
            if self.relation_model == "attribute_node":
                facts = self.store.get_assoc(node.id) or []
            else:
                facts = self.store.get_facts(node.id) or []
            if not children and not facts:
                return None, None
            seen: set[str] = {node.id}
            view_nodes: list[Node] = [node]
            for child in children:
                if child.id not in seen:
                    seen.add(child.id)
                    view_nodes.append(child)
            for edge in facts:
                for eid in (edge.source_id, edge.target_id):
                    if eid not in seen:
                        endpoint = self.store.get_node(eid)
                        if endpoint is not None:
                            seen.add(eid)
                            view_nodes.append(endpoint)
            return view_nodes, facts

        def _call_select(view_nodes, facts):
            """渲染 + 调 select_facts；解析失败返回 None。"""
            material = renderer.render_facts(view_nodes, facts, mode=self.relation_model)
            try:
                return self.llm.call(
                    purpose="select_facts",
                    nodes_in=view_nodes,
                    free_args={
                        "material": material,
                        "query": query,
                        "accumulated_summary": _summarize_for_prompt(
                            accumulated, self.summary_max_nodes
                        ),
                    },
                ) or []
            except LLMParseError:
                return None

        def _consume(indices, view_nodes, facts):
            """编号映射回节点 / 事实边（1-based），补入 accumulated。

            返回 (新增节点列表, 是否撞 max_accumulated cap)。
            """
            nonlocal used_tokens
            n_nodes = len(view_nodes)
            newly: list[Node] = []
            hit_cap = False
            for idx in indices:
                if hit_cap:
                    break
                zero_idx = idx - 1
                if zero_idx < 0:
                    continue
                if zero_idx < n_nodes:
                    # 节点条目 → 加入 accumulated
                    sel_node = view_nodes[zero_idx]
                    if sel_node.id not in visited:
                        visited.add(sel_node.id)
                        accumulated.append(sel_node)
                        used_tokens += self.token_budget.estimate_node(
                            sel_node, estimate_cache
                        )
                        newly.append(sel_node)
                        if len(accumulated) >= self.max_accumulated_nodes:
                            hit_cap = True
                else:
                    # 事实边条目 → 记录边 + 补入端点
                    edge_idx = zero_idx - n_nodes
                    if 0 <= edge_idx < len(facts):
                        edge = facts[edge_idx]
                        if edge.id not in selected_edge_ids:
                            selected_edge_ids.add(edge.id)
                            selected_edges.append(edge)
                        for eid in (edge.source_id, edge.target_id):
                            if eid not in visited:
                                endpoint = self.store.get_node(eid)
                                if endpoint is not None:
                                    visited.add(eid)
                                    accumulated.append(endpoint)
                                    used_tokens += self.token_budget.estimate_node(
                                        endpoint, estimate_cache
                                    )
                                    newly.append(endpoint)
                                    if len(accumulated) >= self.max_accumulated_nodes:
                                        hit_cap = True
                                        break
            return newly, hit_cap

        depth = 0
        while frontier and depth < self.max_rounds:
            if (
                len(accumulated) >= self.max_accumulated_nodes
                or used_tokens >= budget
            ):
                break

            # 预备每节点单视图 + 渲染 token 估算（无可扩展内容者剔除）
            prepared: list = []
            for node in frontier:
                view_nodes, facts = _node_view(node)
                if view_nodes is None:
                    continue
                est = self.token_budget.estimate(
                    renderer.render_facts(view_nodes, facts, mode=self.relation_model)
                )
                prepared.append((node, view_nodes, facts, est))

            if not prepared:
                break

            # 贪心按层打包：合计 ≤ pack_budget 合并为一批；单节点超限自成一批
            batches: list[list] = []
            cur: list = []
            cur_tok = 0
            for item in prepared:
                if cur and cur_tok + item[3] > pack_budget:
                    batches.append(cur)
                    cur = []
                    cur_tok = 0
                cur.append(item)
                cur_tok += item[3]
            if cur:
                batches.append(cur)

            next_frontier: list[Node] = []
            next_seen: set[str] = set()
            stop = False
            for batch in batches:
                if (
                    len(accumulated) >= self.max_accumulated_nodes
                    or used_tokens >= budget
                ):
                    stop = True
                    break

                if len(batch) == 1:
                    _node, view_nodes, facts, _est = batch[0]
                    indices = _call_select(view_nodes, facts)
                    if indices is None:
                        continue
                    newly, hit_cap = _consume(indices, view_nodes, facts)
                else:
                    # 合并各节点视图（去重）为一次调用
                    merged_nodes: list[Node] = []
                    merged_seen: set[str] = set()
                    merged_facts: list[Edge] = []
                    merged_fact_ids: set[str] = set()
                    for _n, vn, fs, _e in batch:
                        for x in vn:
                            if x.id not in merged_seen:
                                merged_seen.add(x.id)
                                merged_nodes.append(x)
                        for e in fs:
                            if e.id not in merged_fact_ids:
                                merged_fact_ids.add(e.id)
                                merged_facts.append(e)
                    indices = _call_select(merged_nodes, merged_facts)
                    if indices is None:
                        # 批量解析失败 → 逐节点回退（spec batch-neighbor-traverse）
                        newly = []
                        hit_cap = False
                        for _n, vn, fs, _e in batch:
                            idx_single = _call_select(vn, fs)
                            if idx_single is None:
                                continue
                            added, cap = _consume(idx_single, vn, fs)
                            newly.extend(added)
                            if cap:
                                hit_cap = True
                                break
                    else:
                        newly, hit_cap = _consume(
                            indices, merged_nodes, merged_facts
                        )

                for n in newly:
                    if n.id not in next_seen:
                        next_seen.add(n.id)
                        next_frontier.append(n)
                if hit_cap:
                    stop = True
                    break

            if stop:
                break
            frontier = next_frontier
            depth += 1

        return accumulated, selected_edges

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

    def _run_postprocess(self, subgraph: Any, ctx: QueryContext) -> Any:
        """阶段 ⑤：针对 Subgraph 的串行 PostprocessPlugin 链。

        后置插件接收 Subgraph 并可转换为自然语言或其他格式。
        兼容旧插件：期望 ``List[Node]`` 的插件经兼容层接收 ``subgraph.nodes``，
        返回的 ``List[Node]`` 自动重建为 ``Subgraph``。
        无后置插件时返回原始 Subgraph。
        """
        from mcs.core.plugin import PluginType
        from mcs.entities.graph import Node, Subgraph

        plugins = self.plugin_manager.get_all(PluginType.POSTPROCESS)
        if not plugins:
            return subgraph
        result: Any = subgraph
        for plugin in plugins:
            if isinstance(result, Subgraph):
                # 兼容层：传 nodes 给旧插件，若返回 list[Node] 则重建 Subgraph
                processed = plugin.process(result.nodes, ctx)
                if isinstance(processed, list) and (
                    not processed or isinstance(processed[0], Node)
                ):
                    result = Subgraph(
                        focus_id=result.focus_id,
                        nodes=processed,
                        edges=_filter_edges_by_nodes(result.edges, processed),
                    )
                else:
                    # 插件返回了其他类型（如 str），直接作为最终结果
                    result = processed
            else:
                result = plugin.process(result, ctx)
        return result

    def _run_postprocess_nodes(
            self, nodes: list[Node], ctx: QueryContext
    ) -> list[Node]:
        """阶段 ⑤ 的旧版：针对 List[Node] 的后处理链（query_nodes 兼容）。"""
        from mcs.core.plugin import PluginType

        plugins = self.plugin_manager.get_all(PluginType.POSTPROCESS)
        if not plugins:
            return nodes
        result: Any = nodes
        for plugin in plugins:
            result = plugin.process(result, ctx)
        return result if isinstance(result, list) else nodes


def _summarize_for_prompt(nodes: list[Node], max_nodes: int = 50) -> str:
    """已累积节点的紧凑上下文：**仅 name**、且只取**最近 max_nodes 个**。

    每次 select_facts 调用都会带上本串。旧实现带 id + content[:200] 的**全量**节点，
    随遍历累积膨胀到 ~15k token、再 × 每条查询十几次调用 → 平方级输入成本
    （实测占查询输入 ~73%）。这里只发 name、并按最近 max_nodes 截断——给 LLM
    "已收集到啥"的上下文足矣（重复选取由 visited 防，不依赖本串）。

    ``max_nodes <= 0`` 关闭本串（返回 (无)）。
    """
    if max_nodes <= 0 or not nodes:
        return "(无)"
    recent = nodes[-max_nodes:]
    names = ", ".join(n.name for n in recent if n.name)
    if not names:
        return "(无)"
    if len(nodes) > len(recent):
        return f"(已收集 {len(nodes)} 项，列最近 {len(recent)} 项) {names}"
    return names


def _filter_edges_by_nodes(
        edges: list[Edge], nodes: list[Node]
) -> list[Edge]:
    """过滤事实边：仅保留两端都在 nodes 中的边。"""
    node_ids = {n.id for n in nodes}
    return [e for e in edges if e.source_id in node_ids and e.target_id in node_ids]

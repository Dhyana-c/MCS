"""图导航 + 遍历原语 —— 供写管线 ingest 关联定位与记忆 agent 导航复用。

本模块**不再提供读查询编排**（5 阶段 query 管线已退役——查询职责归记忆 agent 的
search/associate/reason 分步游走，见 openspec change `retire-framework-query-pipeline`）。
保留下列图底座原语：

- ``locate_seeds`` / ``_locate_seeds``：种子定位（ENTRY + TRIM 插件链），供 agent
  ``search`` 与写管线 ``query_nodes`` 复用。
- ``_traverse``：批量事实 BFS 遍历（双角色 select_facts + token 预算 + visited），
  供写管线 ``query_nodes`` 关联定位使用。
- ``query_nodes``：写管线阶段② 专用轻量遍历（限深、``select_facts_write``、无 ④⑤）。
- ``get_related_events`` / ``narrative_timeline`` / ``token_budget``：agent 导航原语。

参见 openspec/specs/lightweight-query/spec.md。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from mcs.core.content_merge import merge_content
from mcs.prompts.select_facts import SelectFactsResult, coerce_select_result

if TYPE_CHECKING:
    from mcs.core.plugin_manager import PluginManager
    from mcs.core.store import StoreInterface
    from mcs.core.token_budget import TokenBudget
    from mcs.entities.graph import Edge, Node
    from mcs.interfaces.llm import LLMInterface

logger = logging.getLogger(__name__)


@dataclass
class QueryContext:
    """贯穿一次图导航 / 遍历调用的轻量上下文（locate_seeds / query_nodes / _traverse）。

    读查询编排退役后，QueryContext 仅保留导航所需字段（ENTRY/TRIM 插件经 ``ctx``
    读取 ``user_input`` / ``universe``）。``accumulated`` / ``visited`` / ``frontier``
    为 ``_traverse`` 内部局部状态、非本类字段。

    参见 openspec/specs/lightweight-query/spec.md "QueryContext 为导航 / 遍历的轻量上下文"。
    """

    system_prompt: str = ""
    user_input: str = ""
    metadata: dict = field(default_factory=dict)
    universe: str | None = None


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
            max_frontier_nodes: int = 500,
            system_prompt: str = "",
            summary_max_nodes: int = 50,
    ):
        self.store = store
        self.llm = llm
        self.plugin_manager = plugin_manager
        self.token_budget = token_budget
        self.max_rounds = max_rounds
        self.max_accumulated_nodes = max_accumulated_nodes
        # frontier 规模安全阀：解耦后 `探索` 不吃 T，used_tokens 不再约束 frontier
        # 增长，max_rounds 只限深度——单轮 next_frontier 宽度需独立阀防 LLM 调用爆炸。
        self.max_frontier_nodes = max_frontier_nodes
        self.system_prompt = system_prompt
        # 每次 select_facts 调用带的「已累积上下文」最多列多少个节点（仅 name）。
        # 旧实现带全量 name+content → 输入平方级膨胀（占查询输入 ~73%）。0 = 关闭。
        self.summary_max_nodes = summary_max_nodes

    # === 公共 API ===

    def query_nodes(
            self,
            text: str,
            max_rounds: int = 1,
            universe: str | None = None,
    ) -> list[Node]:
        """写管线阶段② 关联定位专用图遍历：种子定位 → 限深 BFS，返回 List[Node]。

        执行 ② 种子定位（ENTRY + TRIM 链）→ ③ 遍历（限 ``max_rounds`` 轮、
        ``select_purpose="select_facts_write"`` 窄召回）；**无 ④ 仲裁 / ⑤ 后处理**
        （读查询编排已退役——见 ``retire-framework-query-pipeline``）。

        ``universe`` 非空时，种子定位 / BFS 限该 universe 内（ingest 期关联定位 MUST
        universe 限域，防 judge_relations 看到跨 universe 候选乱连边 / 误判互斥）；
        ``None`` 不过滤（默认现实世界行为，向后兼容）。
        """
        ctx = QueryContext(
            system_prompt=self.system_prompt,
            user_input=text,
            universe=universe,
        )

        # ② 种子定位（QUERY_PREPROCESS 已随读查询编排退役，直传 text）
        seeds = self._locate_seeds(text, ctx)

        # ③ 遍历（限深 max_rounds，窄召回 select_facts_write）
        accumulated, _ = self._traverse(
            seeds, text, ctx, select_purpose="select_facts_write",
            max_rounds=max_rounds,
        )
        return list(accumulated)

    def locate_seeds(self, query: str, universe: str | None = None) -> list[Node]:
        """公共薄方法：种子定位（阶段②），供外部（如 ``mcs_agent.search``）复用。

        构造临时 ``QueryContext`` 后调 ``_locate_seeds``——与 ``query_nodes`` 内部的
        种子定位逐字等价。

        ``universe`` 非空时种子限该 universe（P7）；``None`` 不过滤（默认）。
        """
        ctx = QueryContext(
            system_prompt=self.system_prompt, user_input=query, universe=universe
        )
        return self._locate_seeds(query, ctx)

    def get_related_events(
        self,
        node_id: str,
        universe: str | None = None,
        limit: int | None = None,
    ) -> list[Node]:
        """定向查事件：绕过载重规则，获取背书此核心节点的事件（时间倒排）。

        宪法载重规则使核心节点 ``get_relations`` 不含事件边。
        查询需要出处/证据时用此方法——独立检索步，不进常驻活跃视图。

        Args:
            node_id: 核心节点 id
            universe: ``None`` = 全返（含跨 universe，查出处）；传值 = 只返该
                universe 事件（叙事时间线用，避免作品纪年与 ISO 混排）。
            limit: 最多返回的事件数（None = 全部）。用于事件层时间倒排截断。
        """
        return self.store.get_related_events(node_id, universe=universe, limit=limit)

    def narrative_timeline(
        self, universe: str, limit: int | None = None
    ) -> list[Node]:
        """叙事时间线：取某 universe **事件层**的事件、按 ``timestamp`` 升序组装。

        查询期组装的虚拟视图——MUST NOT 创建节点、MUST NOT 把作品纪年盖到其他
        universe 的时间轴（每 universe 一条独立时间轴）。排序按 universe 内
        timestamp 语义（现实 ISO / 作品数字年；``timestamp_sort_value`` 解析），
        无法解析（含无 timestamp）的事件**垫底**（升序排在末尾）、同值按 id 保确定性。
        Phase 1 仅数字年纪年（"184" / "200 年"）保证顺序；"建安五年"等混合纪年
        需 Phase 2 归一化。

        Args:
            universe: 时间线所属 universe（作品 id 或 ``"__reality__"``）。
            limit: 最多返回的事件数（None = 全部），从时间线**头部**截取。
        """
        from mcs.entities.graph import CLASS_EVENT
        from mcs.utils.timestamps import timestamp_sort_value

        events = [
            n for n in self.store.get_nodes_by_class(CLASS_EVENT)
            if n.universe == universe
        ]

        def _key(node: Node) -> tuple[int, float, str]:
            meta = (node.extensions or {}).get("event_meta", {})
            ts = meta.get("timestamp", "") if isinstance(meta, dict) else ""
            v = timestamp_sort_value(ts)
            # 升序时间线：可解析的按时间升序在前；解析失败（-inf）垫底在末尾
            if v == float("-inf"):
                return (1, 0.0, node.id)
            return (0, v, node.id)

        events.sort(key=_key)
        if limit is not None:
            events = events[:limit]
        return events

    # === 阶段辅助方法 ===

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

        # universe 限域：仅保留同 universe 候选（ingest 期关联定位 MUST universe 限域，
        # 防 judge_relations 看到跨 universe 候选乱连边 / 误判互斥；None = 不过滤）
        if ctx.universe is not None:
            accumulated = [n for n in accumulated if n.universe == ctx.universe]
        return accumulated

    def _traverse(
            self,
            seeds: list[Node],
            query: str,
            ctx: QueryContext,
            select_purpose: str = "select_facts_write",
            max_rounds: int | None = None,
    ) -> tuple[list[Node], list[Edge]]:
        """阶段 ③：批量事实 BFS 遍历（双角色解耦 + 预算分离）。

        四工作区（§4.3）：
          - **积累区**（accumulated）：进 LLM 的输出集（`结果` 角色），逐轮累积，占
            token_budget（≤ T），为 ``_traverse`` 的返回集
          - **活跃区**（active）：本轮待 LLM 推理/筛选的候选，占 T − 积累区
          - **visited**：已处理节点 id，去重防重复遍历（仅存 id，不进 LLM）
          - **frontier**：BFS 待扩展节点队列（`探索` 角色，仅存引用、不进 LLM、
            不吃 T、遍历结束丢弃）

        **双角色解耦**：``select_facts`` 同一次调用输出 ``{result, frontier}`` 两维——
        `结果`/两者 → accumulated（吃 T）；`探索`/两者 → 下一轮 frontier（不吃 T）。
        探索口径宽（保召回 / 广探索）、结果口径严（控进 LLM 规模），二者成员可不同。
        frontier 用完即弃（不返回），其规模由 ``max_frontier_nodes`` 阀兜。

        预算分离：积累区 + 活跃区 ≤ T。积累区逐轮变大、活跃区空间随之收缩，
        逼近 token_budget 即停。

        逐层扩展：每层把待扩展节点的活跃双向视图按渲染 token 贪心打包到
        ``T − 积累区``——合计 ≤ 余量的多个节点合并进**一次**事实筛选调用（purpose 取 ``select_purpose``；
        spec query-pipeline「按层分批、富余合并」）；单节点视图已超余量
        则自成一批。批量调用解析失败时**逐节点回退**，保证遍历不中断
        （spec batch-neighbor-traverse）。

        返回 (accumulated_nodes, selected_fact_edges)。
        """
        if not seeds:
            return [], []

        # 深度上界：显式传入优先（query_nodes 限深用），否则用实例 max_rounds。
        # 避免修改 self.max_rounds（非线程安全、可重入风险）。
        rounds_limit = max_rounds if max_rounds is not None else self.max_rounds

        from mcs.core.context_renderer import ContextRenderer
        from mcs.core.errors import LLMParseError

        # ── 四工作区 ──
        visited: set[str] = set()           # 已处理节点 id（簿记，不进 LLM）
        accumulated: list[Node] = []        # 积累区（进 LLM，占 token_budget）
        selected_edges: list[Edge] = []
        selected_edge_ids: set[str] = set()
        estimate_cache: dict[str, int] = {}
        used_tokens = 0                     # 积累区已用 token
        budget = self.token_budget.T        # token_budget（积累区上限 ≤ T）
        renderer = ContextRenderer(self.plugin_manager)

        # read-repair 同名合并：(name, universe) → 首次出现的节点 id
        # 同名字面识别——同名当场可见、零成本；同名≠同义需消歧（Phase 1 不做 LLM 判定）。
        # 键含 universe：跨 universe 同名不合并（演义曹操 ≠ 正史曹操）。
        name_index: dict[tuple[str, str], str] = {}     # (name, universe) → node_id
        merged_into: dict[str, str] = {}    # node_id → target_id（被合并掉的）
        repaired_ids: set[str] = set()      # 本次遍历被合并改写的 target（遍历末落盘）

        # frontier（BFS 待扩展队列，仅存 id→Node 引用，不进 LLM）
        # 种子只进 frontier（去重）：不预填 accumulated、不进初始 visited、不预计
        # used_tokens（对齐 token-budget-traverse「accumulated 初始为空、种子经 LLM
        # 筛选后才加入」，修正既有 drift）。种子在首轮 `_node_view` 中作 view_nodes[0]
        # 经 LLM 双角色评估决定归属。visited 由 `_consume` 在 LLM 选中时统一加——
        # 种子绝不进初始 visited，否则首轮即便标 `结果` 也会被 `_consume` 的
        # `if node.id in visited` 跳过、永失 accumulated（确定性 bug）。
        frontier: list[Node] = []
        seen_seed: set[str] = set()
        for seed in seeds:
            if seed.id not in seen_seed:
                seen_seed.add(seed.id)
                frontier.append(seed)

        def _try_read_repair(node: Node) -> Node:
            """read-repair 同名合并：同名节点合并到首次遇到的那一个。

            - 同名字面识别（零成本）
            - 合并方式：别名并入 + content 合并（公共 helper；非子串不碰、被并方节点保留）
              节点对象，遍历结束经 ``_persist_read_repairs`` 标脏落盘（内存与 DB 一致；
              被并方节点不删除，仅目标节点内容变更）
            - 合并后用 estimate_node 重算 token 差值（铁律一：口径 == 渲染）
            - 超 T 则挂起（不合并，保留两个节点）
            - 同名≠同义需消歧：Phase 1 不做 LLM 判定，仅字面同名合并

            返回合并后的有效节点（可能是已有的那个，也可能是原节点）。
            """
            nonlocal used_tokens
            name = node.name
            key = (name, node.universe)
            if not name or key not in name_index:
                # 首次遇到此 (名字, universe)
                name_index[key] = node.id
                return node

            target_id = name_index[key]
            if target_id == node.id:
                return node  # 自身，跳过

            target = self.store.get_node(target_id)
            if target is None:
                name_index[key] = node.id
                return node

            # 找到积累区中的 target 实例
            target_node = None
            for acc_node in accumulated:
                if acc_node.id == target_id:
                    target_node = acc_node
                    break
            if target_node is None:
                # target 不在积累区（不应发生，但防御）
                name_index[key] = node.id
                return node

            # 记录合并前 token
            old_target_token = self.token_budget.estimate_node(
                target_node, estimate_cache
            )

            # content 合并（公共 helper；读路径不传 LLM → 非子串不碰、被并方节点保留）
            extra_content = node.content
            merged_content = merge_content(
                target_node.content or "",
                extra_content or "",
                merge_llm=None,
            )

            # 临时修改 content 用于重算 token
            saved_content = target_node.content
            target_node.content = merged_content
            # 清缓存，强制重算（P2-4：保持 estimate_cache 与实际一致）
            estimate_cache.pop(target_id, None)
            new_target_token = self.token_budget.estimate_node(
                target_node, estimate_cache
            )
            delta = new_target_token - old_target_token

            # 守门：合并后是否超 T
            if used_tokens + delta > budget:
                # 超 T → 挂起（恢复 content，不合并）
                target_node.content = saved_content
                estimate_cache.pop(target_id, None)
                # 恢复缓存为旧值
                estimate_cache[target_id] = old_target_token
                return node

            # 合并确认：used_tokens 增量
            used_tokens += delta

            # 别名追加（用 setdefault 模式，与 write_pipeline 一致）
            aliases = target_node.extensions.setdefault(
                "alias_index", {}
            ).setdefault("aliases", [])
            if node.name and node.name not in aliases and node.name != target_node.name:
                aliases.append(node.name)

            # 标记此节点已被合并；target 内容已改写，记入待落盘集
            merged_into[node.id] = target_id
            repaired_ids.add(target_id)
            visited.add(node.id)
            return target_node

        def _node_view(node: Node):
            """单节点活跃双向视图 (view_nodes, relation_edges)。

            无下钻成员且无关系边时（修法 A'，关掉孤立/叶子节点静默丢弃）：
            - **未裁决**的无视图中心（=种子，不在 visited）→ 返回 ``([node], [])``
              单节点视图，交 LLM 评估、有机会被标 `结果`；
            - **已 visited** 的无视图叶子（探索跳板，已裁决）→ 返回 ``(None, None)``
              跳过，避免空转 re-eval（`_consume` 会因 visited 跳过、无新增）。
            """
            children = self.store.get_out_hierarchy(node.id, universe=node.universe) or []
            facts = self.store.get_relations(node.id) or []
            if not children and not facts:
                if node.id in visited:
                    return None, None
                return [node], []
            seen: set[str] = {node.id}
            view_nodes: list[Node] = [node]
            for child in children:
                if child.id not in seen:
                    seen.add(child.id)
                    view_nodes.append(child)
            # 关系边端点批量取节点（消除 N+1：一次 get_nodes 取回，缺省跳过）
            endpoint_ids: list[str] = []
            for edge in facts:
                for eid in (edge.source_id, edge.target_id):
                    if eid not in seen:
                        seen.add(eid)
                        endpoint_ids.append(eid)
            for endpoint in self.store.get_nodes(endpoint_ids):
                view_nodes.append(endpoint)
            return view_nodes, facts

        def _call_select(view_nodes, facts):
            """渲染 + 调 select_facts；返回 SelectFactsResult，解析失败返回 None。"""
            material = renderer.render_facts(view_nodes, facts)
            try:
                raw = self.llm.call(
                    purpose=select_purpose,
                    nodes_in=view_nodes,
                    free_args={
                        "material": material,
                        "query": query,
                        "accumulated_summary": _summarize_for_prompt(
                            accumulated, self.summary_max_nodes
                        ),
                    },
                )
                if raw is None:
                    return SelectFactsResult([], [])
                # 归一（真 LLM 经 parse 已是 SelectFactsResult；mock 返回 flat 列表
                # 在此归一为"两者"——保旧测试行为：选中即进双方）。
                return coerce_select_result(raw)
            except LLMParseError:
                return None

        def _consume(sel: SelectFactsResult, view_nodes, facts):
            """按角色把 select 结果（1-based 编号）分流。

            - `结果`（result）→ accumulated（+visited、+used_tokens；事实边记
              selected_edges、端点入 accumulated）；新节点先走 read-repair 同名合并。
            - `探索`（frontier）→ 下一轮 frontier（+visited，不吃 token、不合并）。
            - 两者（同一编号在两列表）→ 同时进双方。

            返回 (frontier_nodes, 是否撞 max_accumulated cap)。frontier_nodes 即
            下一轮待扩展节点（探索 / 两者角色产出）。
            """
            nonlocal used_tokens
            n_nodes = len(view_nodes)
            frontier_nodes: list[Node] = []
            hit_cap = False

            def _route(node: Node, want_result: bool, want_frontier: bool) -> bool:
                """按角色路由单个节点；返回是否撞 accumulated cap。

                visited 在此**统一**加（结果走 read-repair 后加，探索直接加），
                使"两者"角色在同一次调用里既进 accumulated 又进 frontier_nodes
                （不会被"结果先加 visited、探索再被 visited 挡"破坏）。
                """
                nonlocal used_tokens
                if node.id in visited:
                    return False
                if want_result:
                    effective = _try_read_repair(node)
                    if effective.id != node.id:
                        # 被合并到已有节点 → 不重复加入 accumulated，也不入 frontier
                        # （同义跳板，target 已在 accumulated）
                        return False
                    visited.add(node.id)
                    accumulated.append(node)
                    used_tokens += self.token_budget.estimate_node(
                        node, estimate_cache
                    )
                    if want_frontier:
                        frontier_nodes.append(node)
                    return len(accumulated) >= self.max_accumulated_nodes
                # 仅探索
                visited.add(node.id)
                frontier_nodes.append(node)
                return False

            want_r = set(sel.result)
            want_f = set(sel.frontier)
            # 结果优先序、去重（"两者"只处理一次）
            ordered: list[int] = []
            seen_idx: set[int] = set()
            for idx in list(sel.result) + list(sel.frontier):
                if idx not in seen_idx:
                    seen_idx.add(idx)
                    ordered.append(idx)

            for idx in ordered:
                if hit_cap:
                    break
                zero_idx = idx - 1
                if zero_idx < 0:
                    continue
                wr = idx in want_r
                wf = idx in want_f
                if zero_idx < n_nodes:
                    # 节点条目
                    if _route(view_nodes[zero_idx], wr, wf):
                        hit_cap = True
                else:
                    # 事实边条目 → 结果角色记边；端点按角色补入
                    edge_idx = zero_idx - n_nodes
                    if 0 <= edge_idx < len(facts):
                        edge = facts[edge_idx]
                        if wr and edge.id not in selected_edge_ids:
                            selected_edge_ids.add(edge.id)
                            selected_edges.append(edge)
                        for eid in (edge.source_id, edge.target_id):
                            endpoint = self.store.get_node(eid)
                            if endpoint is None:
                                continue
                            if _route(endpoint, wr, wf):
                                hit_cap = True
                                break
            return frontier_nodes, hit_cap

        depth = 0
        while frontier and depth < rounds_limit:
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
                    renderer.render_facts(view_nodes, facts)
                )
                prepared.append((node, view_nodes, facts, est))

            if not prepared:
                break

            # 活跃区预算 = T − 积累区已用（动态收缩）
            active_budget = budget - used_tokens
            if active_budget <= 0:
                break

            # 贪心按层打包：合计 ≤ active_budget 合并为一批；单节点超限自成一批
            batches: list[list] = []
            cur: list = []
            cur_tok = 0
            for item in prepared:
                if cur and cur_tok + item[3] > active_budget:
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
                    sel = _call_select(view_nodes, facts)
                    if sel is None:
                        continue
                    newly, hit_cap = _consume(sel, view_nodes, facts)
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
                    sel = _call_select(merged_nodes, merged_facts)
                    if sel is None:
                        # 批量解析失败 → 逐节点回退（spec batch-neighbor-traverse）
                        newly = []
                        hit_cap = False
                        for _n, vn, fs, _e in batch:
                            sel_single = _call_select(vn, fs)
                            if sel_single is None:
                                continue
                            added, cap = _consume(sel_single, vn, fs)
                            newly.extend(added)
                            if cap:
                                hit_cap = True
                                break
                    else:
                        newly, hit_cap = _consume(
                            sel, merged_nodes, merged_facts
                        )

                # frontier 安全阀：next_frontier 达 max_frontier_nodes 即停止入队
                # （当前轮 `结果` 已进 accumulated，非整体终止；区别于 max_accumulated 撞阀）
                for n in newly:
                    if len(next_frontier) >= self.max_frontier_nodes:
                        break
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

        # read-repair 改写了 store 内共享节点（content/别名）——标脏落盘，
        # 否则内存与 DB 静默分叉、重启后合并丢失。
        if repaired_ids:
            self._persist_read_repairs(repaired_ids)

        return accumulated, selected_edges

    def _persist_read_repairs(self, node_ids: set[str]) -> None:
        """把 read-repair 改写的节点标脏并落盘（duck-typed，仅 SQLiteStore 生效）。

        失败不中断查询（读路径），仅告警——脏标记已留，下次任意 flush 收敛。
        """
        mark = getattr(self.store, "mark_node_dirty", None)
        flush = getattr(self.store, "flush_changes", None)
        if not callable(mark):
            return
        try:
            for nid in node_ids:
                mark(nid)
            if callable(flush) and getattr(self.store, "conn", None) is not None:
                flush()
        except Exception:
            logger.warning("read-repair 持久化失败（脏标记已留，下次 flush 收敛）", exc_info=True)

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

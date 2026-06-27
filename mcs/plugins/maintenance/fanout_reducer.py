"""FanoutReducerPlugin - 主动守门 + 整窗单次裂变。

邻域即将超 T 时立即触发裂变：取中心 + 全部一跳子节点一次性喂 decide_hub，
不分批、不折半重试。重组产出 hub（提拔/新建/合并）后以纯下行边重连：
删 C→M、建 C→H、建 H→M（无上行边）。全局适用于任意超预算节点。
"""

from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING, Any

from mcs.core.errors import LLMCallError
from mcs.core.plugin import PluginType
from mcs.entities.graph import (
    CLASS_CONCEPT,
    CLASS_FACT,
    CORE_NODE_CLASSES,
    EDGE_ASSOC,
    SEED_ROOT_ID,
    SEED_ROOT_NAME,
)
from mcs.interfaces.compaction_plugin import CompactionPluginInterface

if TYPE_CHECKING:
    from collections.abc import Callable

    from mcs.core.plugin_manager import PluginContext
    from mcs.core.store import StoreInterface
    from mcs.entities.graph import Edge, Node

logger = logging.getLogger(__name__)


class FanoutReducerPlugin(CompactionPluginInterface):
    """主动守门 + 整窗单次裂变。

    当节点一跳邻域即将超 T 时立即触发裂变——取中心 + 全部一跳子节点一次喂
    ``decide_hub``（不分批、不折半重试），产出 hub 后以纯下行边重连（删 C→M、
    建 C→H、建 H→M），递归直到图中处处 ≤ T。

    ``maintain_root=True`` 时，额外维护持久虚拟根 ``__seed_root__``：
    把新概念挂到根下（单条下行 root→concept），并从根开始递归分层。
    """

    def __init__(self, config: dict | None = None) -> None:
        super().__init__(config)
        cfg = config or {}
        # 邻居数低于 floor 一定不触发（避免极端：节点很大时几个邻居就归纳）
        self.floor: int = cfg.get("floor", 16)
        self.token_budget: Any = None
        # 守门估算共用的真实渲染器（注入后估算口径 == 渲染口径，铁律一）；
        # 单测未注入时为 None，回退逐节点估算之和。
        self.renderer: Any = None
        # 维护持久虚拟根（分层种子图）；默认开启，保证图中处处一跳邻域 ≤ T
        self.maintain_root: bool = bool(cfg.get("maintain_root", True))
        # 单次 ingest 递归归纳的硬上限，防止 decide_hub 抖动导致失控
        self.max_reorg: int = int(cfg.get("max_reorg", 200))

    # === Plugin 基类方法 ===

    def get_name(self) -> str:
        return "fanout_reducer"

    # === 插件生命周期 ===

    def initialize(self, context: PluginContext) -> None:
        self.token_budget = context.token_budget
        self.renderer = getattr(context, "context_renderer", None)

    def shutdown(self) -> None:
        return None

    # === CompactionPluginInterface ===

    def should_run(
        self, changed_nodes: list[Node], store: StoreInterface
    ) -> bool:
        # 预算压力（root / changed / 受影响节点任一邻域超 T）→ 需要裂变
        if self._has_budget_pressure(changed_nodes, store):
            return True
        # 根维护与预算闸门解耦：maintain_root 且本次有新概念时也要跑——把新概念挂到
        # 持久根。否则无预算压力的图（小语料 / 大窗口 T / 整篇摄入）永不建根、查询
        # 无从沿出边下钻（曾导致整图扁平、文档级召回为 0）。
        if self.maintain_root and any(
            getattr(n, "node_class", CLASS_CONCEPT) in CORE_NODE_CLASSES for n in changed_nodes
        ):
            return True
        return False

    def _has_budget_pressure(
        self, changed_nodes: list[Node], store: StoreInterface
    ) -> bool:
        """是否存在预算压力：root / changed / 受影响节点 任一邻域渲染超 T。"""
        # 1. root 始终检查（不变量含虚拟根）
        root = store.get_node(SEED_ROOT_ID)
        if root is not None:
            if self._exceeds_budget(root, store.get_out_hierarchy(root.id)):
                return True

        # 2. changed_nodes 检查
        for node in changed_nodes:
            if self._exceeds_budget(node, store.get_out_hierarchy(node.id)):
                return True

        # 3. 受影响节点检查（与 changed_nodes 有边的节点）
        changed_ids = {n.id for n in changed_nodes}
        affected_ids: set[str] = set()
        for node in changed_nodes:
            for neighbor in store.get_out_hierarchy(node.id):
                if neighbor.id not in changed_ids:
                    affected_ids.add(neighbor.id)

        for nid in affected_ids:
            node = store.get_node(nid)
            if node is not None:
                if self._exceeds_budget(node, store.get_out_hierarchy(nid)):
                    return True

        return False

    def run(
        self,
        changed_nodes: list[Node],
        store: StoreInterface,
        llm_caller: Callable,
    ) -> None:
        # 重活（受影响节点裂变 + hub 复用边吸收）只在预算压力下做：全量收集 +
        # 全图扫描成本高，无超预算节点时跳过。
        if self._has_budget_pressure(changed_nodes, store):
            # 收集需检查的完整节点集：changed + 受影响 + root
            nodes_to_check = self._collect_all_affected(changed_nodes, store)
            # 收集所有新 hub，用于后续递归守门检查
            all_new_hubs: list[Node] = []
            for node in nodes_to_check:
                all_new_hubs.extend(
                    self._compact_node(node, store, llm_caller)
                )
            # 对新 hub 递归守门检查（不限于 maintain_root 模式）
            self._guard_new_hubs(all_new_hubs, store, llm_caller)
            # hub 复用（边吸收）
            self._absorb_hub_edges(store)

        # 根维护无条件进行（与预算闸门解耦）：把新概念挂到持久根 + 根预算检查；
        # 重的 decide_hub 裂变在 _maintain_seed_root 内部按 _exceeds_budget 自门控，
        # 故无预算压力时它只做廉价的挂边、不调用 LLM。
        if self.maintain_root:
            self._maintain_seed_root(changed_nodes, store, llm_caller)

    def _collect_all_affected(
        self, changed_nodes: list[Node], store: StoreInterface
    ) -> list[Node]:
        """收集所有需守门检查的节点：changed + 受影响 + root。

        受影响节点 = 与 changed_nodes 有边的节点（边变化可能使其邻域扩大）。
        root 始终检查（不变量含虚拟根）。
        """
        result: list[Node] = list(changed_nodes)
        seen: set[str] = {n.id for n in changed_nodes}

        # 受影响节点（与 changed 有边）
        for node in changed_nodes:
            for neighbor in store.get_out_hierarchy(node.id):
                if neighbor.id not in seen:
                    seen.add(neighbor.id)
                    result.append(neighbor)

        # root（始终检查）
        root = store.get_node(SEED_ROOT_ID)
        if root is not None and root.id not in seen:
            result.append(root)

        return result

    def _compact_node(
        self,
        node: Node,
        store: StoreInterface,
        llm_caller: Callable,
    ) -> list[Node]:
        """对单个节点执行主动守门 + 整窗单次裂变。

        取中心 + 全部一跳子节点一次性喂 decide_hub（不分批、不折半重试），
        递归直到邻域 ≤ T 或达 max_reorg 上限。
        """
        new_hubs: list[Node] = []
        reorgs = 0
        while reorgs < self.max_reorg:
            neighbors = store.get_out_hierarchy(node.id)
            if not self._exceeds_budget(node, neighbors):
                break
            if len(neighbors) < 2:
                logger.warning(
                    "节点 '%s' 邻域超预算但邻居 < 2，无法聚类", node.name
                )
                break
            # 整窗单次：中心 + 全部一跳子节点一次喂 decide_hub
            decision = self._decide_hub(node, neighbors, llm_caller)
            if decision is None:
                break
            batch_hubs = self._reorganize_multi(node, decision, neighbors, store)
            new_hubs.extend(batch_hubs)
            reorgs += 1
            # 若本批未产出 hub，退出防死循环
            if not batch_hubs:
                break
            # 进展检查：邻居数必须下降
            after_neighbor_count = len(store.get_out_hierarchy(node.id))
            if after_neighbor_count >= len(neighbors):
                logger.warning(
                    "节点 '%s' 本轮重组未减少邻居数（%d → %d），退出",
                    node.name, len(neighbors), after_neighbor_count,
                )
                break
        if reorgs >= self.max_reorg:
            logger.warning(
                "节点 '%s' 撞 max_reorg 上限（%d），邻域可能仍超预算",
                node.name, self.max_reorg,
            )
        return new_hubs

    def _guard_new_hubs(
        self,
        new_hubs: list[Node],
        store: StoreInterface,
        llm_caller: Callable,
    ) -> None:
        """对新 hub 递归守门检查：若新 hub 邻域仍超预算，继续裂变。"""
        reorgs = 0
        queue: list[str] = [h.id for h in new_hubs]
        while queue and reorgs < self.max_reorg:
            nid = queue.pop()
            node = store.get_node(nid)
            if node is None:
                continue
            neighbors = store.get_out_hierarchy(nid)
            if not self._exceeds_budget(node, neighbors):
                continue
            if len(neighbors) < 2:
                continue
            decision = self._decide_hub(node, neighbors, llm_caller)
            if decision is None:
                continue
            before = len(store.get_out_hierarchy(nid))
            hub_list = self._reorganize_multi(node, decision, neighbors, store)
            reorgs += 1
            for hub in hub_list:
                queue.append(hub.id)
            if len(store.get_out_hierarchy(nid)) < before:
                queue.append(nid)

        if reorgs >= self.max_reorg:
            logger.warning(
                "新 hub 守门检查撞 max_reorg 上限（%d），递归归纳提前终止",
                self.max_reorg,
            )

    def _maintain_seed_root(
        self,
        changed_nodes: list[Node],
        store: StoreInterface,
        llm_caller: Callable,
    ) -> None:
        """维护持久虚拟根 + 递归分层种子图。

        1) 确保 ``__seed_root__`` 存在；2) 把本次新建的概念挂到根下（单条下行
        root→concept）；3) 从根开始递归：任一节点扇出超预算就整窗 ``decide_hub``
        提/建中间 hub、把全部子节点重挂到 hub 下，直至每层扇出 ≤ 窗口（或达
        max_reorg 上限）；4) 把根 + 新增/改动的 hub 追加进 ``changed_nodes``。
        """
        from mcs.entities.graph import Node

        root = store.get_node(SEED_ROOT_ID)
        if root is None:
            root = Node(
                id=SEED_ROOT_ID, name=SEED_ROOT_NAME, content="",
                node_class=CLASS_CONCEPT, extensions={"hub": True},
            )
            store.add_node(root)

        # 新概念**仅在"孤儿"（零关系关联）时**挂根（单条下行 root→concept，D6）。
        # 有关系关联者经字面入口（alias_entry）+ 关系 BFS 可达，不挂根——避免 root
        # 扁平化、让图成森林。此处在阶段⑥运行，stage⑤ 的关系边已落库，判定准确。
        # 关系关联 = 该节点作任一端的 关联 / 互斥 边（get_relations 反查）。
        for n in list(changed_nodes):
            if n.id == root.id:
                continue
            if getattr(n, "node_class", CLASS_CONCEPT) not in CORE_NODE_CLASSES or not store.get_node(n.id):
                continue
            if store.get_relations(n.id):
                continue  # 有关系关联 → 不挂根
            store.add_edge(root.id, n.id, type=EDGE_ASSOC)

        # 递归分层（自根向下；进展检查 + max_reorg 双重防死循环）
        affected: dict[str, Node] = {root.id: root}
        queue: list[str] = [root.id]
        reorgs = 0
        while queue and reorgs < self.max_reorg:
            nid = queue.pop()
            node = store.get_node(nid)
            if node is None:
                continue
            neighbors = store.get_out_hierarchy(nid)
            if not self._exceeds_budget(node, neighbors):
                continue
            if len(neighbors) < 2:
                continue
            # 整窗单次裂变
            decision = self._decide_hub(node, neighbors, llm_caller)
            if decision is None:
                continue
            before = len(store.get_out_hierarchy(nid))
            new_hubs = self._reorganize_multi(node, decision, neighbors, store)
            reorgs += 1
            for hub in new_hubs:
                affected[hub.id] = hub
                queue.append(hub.id)  # 新 hub 自身可能超预算 → 继续分层
            if len(store.get_out_hierarchy(nid)) < before:
                queue.append(nid)  # 仍可能超预算，继续收敛

        if reorgs >= self.max_reorg:
            logger.warning(
                "撞 max_reorg 上限（%d），递归归纳提前终止；图中可能仍有超预算节点",
                self.max_reorg,
            )

        for nd in affected.values():
            if nd not in changed_nodes:
                changed_nodes.append(nd)

    def _absorb_hub_edges(self, store: StoreInterface) -> None:
        """hub 复用（边吸收）：一跳子节点 ⊇ hub 全部成员的节点改连 hub。

        若某节点 X 的一跳子节点集合包含 hub H 的全部成员 M（M ⊆ children(X)），
        则把 X 到 M 各成员的直接边替换为单条 X → H：减边、减扇出、复用已有 hub。

        净减边判据：仅当 ``|M| ≥ 2`` 才吸收——删 |M| 条加 1 条，净 -（|M|-1）。
        骨架识别依据节点 ``hub`` 标记（``hub is True``），不依赖边方向。

        统一模型下组织层级用 ``关联`` 边 + hub 标记表达（无独立层级边）：吸收扫描
        ``关联`` 出边。语义为 Phase B（边吸收任务 #25）的深度行为，此处为机械翻译。
        """
        # 一次遍历：节点 → 关联出边目标集合（吸收是层级重连，互斥边不参与）
        out_children: dict[str, set[str]] = {}
        for edge in store.get_all_edges():
            if edge.type != EDGE_ASSOC:
                continue
            out_children.setdefault(edge.source_id, set()).add(edge.target_id)

        nodes = store.get_all_nodes()
        hubs = [n for n in nodes if n.hub]

        for hub in hubs:
            # hub 的概念成员（关联出边目标中非 hub 者）。复用上方 out_children 映射，
            # 避免 per-hub 调 get_all_edges（O(N_hub × E) → O(E)）。
            hub_members: set[str] = set()
            for tid in out_children.get(hub.id, ()):
                member = store.get_node(tid)
                if member is not None and not member.hub:
                    hub_members.add(tid)
            # 净减边判据：至少 2 个成员才有收益
            if len(hub_members) < 2:
                continue

            for node in nodes:
                if node.id == hub.id or node.hub:
                    continue  # hub 不吸收其他 hub 的边（避免层级缠绕）
                children = out_children.get(node.id)
                if not children or not hub_members.issubset(children):
                    continue
                # 吸收：删 X→各成员（关联边），加 X→hub
                for m_id in hub_members:
                    for e in store.get_edges_between(node.id, m_id):
                        if e.type == EDGE_ASSOC:
                            store.delete_edge(e.id)
                            break
                store.add_edge(node.id, hub.id, type=EDGE_ASSOC)
                # 同步更新映射，供后续 hub 判定
                children.difference_update(hub_members)
                children.add(hub.id)
                logger.info(
                    "边吸收：节点 %s → hub %s（%d 条边 → 1 条）",
                    node.name, hub.name, len(hub_members),
                )

    # === 邻域估算 ===

    def _neighborhood_tokens(self, node: Node, neighbors: list[Node]) -> int:
        """估算「node + 邻居」邻域的渲染 token，与实际 LLM 渲染逐字一致（铁律一）。

        注入了 ``renderer`` 时：直接走 ``ContextRenderer.render([node, *neighbors],
        "decide_hub")``——与 decide_hub / 导航 / 遍历的实际渲染同口径（焦点全文、邻居
        降摘要、name==content 去重、extensions 贡献全部一致）。
        未注入 renderer（单测）时：回退为逐节点估算之和（保守近似）。
        """
        tb = self.token_budget
        if self.renderer is not None:
            return tb.estimate(self.renderer.render([node, *neighbors], "decide_hub"))
        total = tb.estimate_node(node)
        for nb in neighbors:
            total += tb.estimate_node(nb)
        return total

    def _exceeds_budget(self, node: Node, neighbors: list[Node]) -> bool:
        """邻域（node + 邻居）渲染 token 累计是否超过上下文窗口（token-aware）。

        无 token_budget 时回退为「邻居 ≥ 32」；有 token_budget 时严格按不变量检查
        （不受 floor 限制）。估算口径与渲染口径一致（经 ``_neighborhood_tokens``）。
        """
        tb = self.token_budget
        if tb is None:
            if len(neighbors) < self.floor:
                return False
            return len(neighbors) >= 32
        return self._neighborhood_tokens(node, neighbors) > tb.T

    # === decide_hub 调用（整窗优先，解析失败折半重试） ===

    def _decide_hub(
        self, node: Node, neighbors: list[Node], llm_caller: Callable
    ) -> Any:
        """调用 decide_hub，整窗优先。LLM 输出被截断（JSON 解析失败）时折半重试。

        774 个子节点一次性喂入时，LLM 的输出 token 可能不够写完所有 member_ids，
        导致 JSON 截断。折半重试确保最终能成功裂变。
        """
        current = list(neighbors)
        for _attempt in range(4):
            try:
                decision = llm_caller(
                    purpose="decide_hub",
                    nodes_in=[node, *current],
                    free_args={},
                )
            except Exception as exc:
                # call() 内部已 retry/backoff，到此处多为不可重试。不可重试错误早停，
                # 避免对错误配置 / 鉴权失败做 4 次无效折半调用；其余（解析相关等）保留折半重试。
                if isinstance(exc, LLMCallError) and not exc.retryable:
                    logger.warning("decide_hub LLM 不可重试错误，放弃本次归纳: %s", exc)
                    return None
                logger.warning("decide_hub LLM 调用异常（将折半重试）", exc_info=True)
                decision = None
            if decision is not None and getattr(decision, "communities", None):
                return decision
            # 解析失败（JSON 截断等）→ 折半重试
            if len(current) <= 20:
                break
            half = max(20, len(current) // 2)
            logger.warning(
                "decide_hub 解析失败（%d 个邻居），折半重试（≤%d）",
                len(current), half,
            )
            current = current[:half]
        return None

    # === 重组相关 ===

    def _is_overbroad_hub(
        self, summary: str, member_count: int, total_neighbors: int
    ) -> bool:
        """检测过宽的合成 hub（catch-all 万能 hub）。

        弱化版本：只检查摘要是否空洞，不再限制成员占比。
        新的聚类三方式（合并/找关键/概括）已从源头避免空洞 hub。
        """
        if not summary or len(summary.strip()) < 3:
            logger.warning("拒绝空洞 hub：摘要过短或为空")
            return True
        # 检测空洞聚合标签（中文按原文匹配；英文大小写不敏感——评测语料为英文）
        cjk_patterns = ["信息碎片", "综合信息", "杂项", "其他", "未分类"]
        en_patterns = [
            "miscellaneous", "uncategorized", "various topics",
            "various concepts", "general information", "comprehensive",
            "assorted", "catch-all", "information cluster", "grab bag",
            "other concepts", "mixed topics",
        ]
        for pattern in cjk_patterns:
            if pattern in summary:
                logger.warning("拒绝空洞 hub：摘要含空洞模式 '%s'", pattern)
                return True
        summary_lc = summary.lower()
        for pattern in en_patterns:
            if pattern in summary_lc:
                logger.warning("拒绝空洞 hub：摘要含空洞模式 '%s'", pattern)
                return True
        return False

    def _find_similar_hub(
        self, summary: str, store: StoreInterface, threshold: float = 0.7
    ) -> Node | None:
        """查找与给定摘要近似的既有 hub（简单词重叠）。

        返回第一个相似度 >= threshold 的 hub，否则 None。
        """
        summary_words = set(summary.lower().split())
        if not summary_words:
            return None
        for node in store.get_all_nodes():
            if not node.hub or node.id == SEED_ROOT_ID:
                continue
            if not node.content:
                continue
            node_words = set(node.content.lower().split())
            if not node_words:
                continue
            overlap = len(summary_words & node_words)
            union = len(summary_words | node_words)
            if union > 0 and overlap / union >= threshold:
                return node
        return None

    def _reorganize(
        self, node: Node, hub: Node, members: list[Node], store: StoreInterface
    ) -> None:
        """纯下行层级重组：把 members 从 node 改挂到 hub。

        对每条有效 (hub H, 成员 M) 执行：
          - 删 node→M
          - 建 node→H
          - 建 H→M
        不建立上行边 M→node（语义关系由独立的语义边承载）。
        """
        if hub.id == node.id:
            return
        for m in members:
            if m.id == hub.id:
                continue
            # 删 node→member（关联边）
            edges = store.get_edges_between(node.id, m.id)
            for e in edges:
                if e.type == EDGE_ASSOC:
                    store.delete_edge(e.id)
                    break
            # 建 hub→member（下行关联边）
            store.add_edge(hub.id, m.id, type=EDGE_ASSOC)
        # 建 node→hub（下行关联边）
        store.add_edge(node.id, hub.id, type=EDGE_ASSOC)

    def _reorganize_multi(
        self,
        node: Node,
        decision: Any,
        neighbors: list[Node],
        store: StoreInterface,
    ) -> list[Node]:
        """一进多出重组：根据 MultiHubDecision 一次造多个 hub。

        三种重组策略全保留：合并同义 / 提拔已有子节点为 hub / 新建概括 hub。
        对每条有效 (hub H, 成员 M)：删 C→M、建 C→H、建 H→M。
        幻觉 id（被关联节点不存在）忽略；未被关联成员留在 C 下不丢。

        Args:
            node: 中心节点（超容量的节点）
            decision: MultiHubDecision（decide_hub.parse 的输出）
            neighbors: 全部一跳子节点
            store: 图存储

        Returns:
            新建的 hub 节点列表
        """
        from mcs.entities.decisions import MultiHubDecision
        from mcs.prompts.decide_hub import validate_and_repair

        # 保存回滚状态（整体快照：保留边 id + 变更跟踪集，回滚不污染持久化）
        rollback_state = store.snapshot()

        # 计算重组前中心节点 + 全部一跳邻域的 token 总量（同口径）
        before_token_total = None
        if self.token_budget is not None:
            before_token_total = self._neighborhood_tokens(node, neighbors)

        # 仅接受 MultiHubDecision
        if not isinstance(decision, MultiHubDecision):
            return []

        # 校验 + 修复
        valid_ids = {n.id for n in neighbors}
        decision = validate_and_repair(decision, valid_ids)

        new_hubs: list[Node] = []
        for comm in decision.communities:
            # 跳过空成员社区（validate 过滤后可能清空，空 hub 只增扇出不降 token → 毒化整批）
            if not comm.member_ids:
                continue
            strategy = getattr(comm, "strategy", "summarize")
            hub = self._create_hub_from_community(comm, store, neighbors)
            if hub is None:
                continue
            members = [n for n in neighbors if n.id in comm.member_ids]
            if strategy == "merge":
                # 宪法：对事实节点只重组不合并（合并会断背书/互斥）。
                # 概念走合并（删除同义节点、合并内容/边），事实走重组（保留节点、仅重挂层级边）。
                concept_members = [
                    m for m in members
                    if getattr(m, "node_class", CLASS_CONCEPT) != CLASS_FACT
                ]
                fact_members = [
                    m for m in members
                    if getattr(m, "node_class", CLASS_CONCEPT) == CLASS_FACT
                ]
                if concept_members:
                    self._merge_synonyms(node, hub, concept_members, store)
                if fact_members:
                    self._reorganize(node, hub, fact_members, store)
            else:
                self._reorganize(node, hub, members, store)
            new_hubs.append(hub)

        # 校验：中心节点全邻域同口径 token 下降才接受，否则回滚
        if not self._validate_reorg(
            store,
            rollback_state,
            center_node=node,
            before_token_total=before_token_total,
        ):
            return []

        return new_hubs

    def _merge_synonyms(
        self,
        node: Node,
        rep: Node,
        members: list[Node],
        store: StoreInterface,
    ) -> None:
        """合并同义概念：把 members 的内容/边合并到 rep，删除 members。

        步骤：
        1. 把每个非代表成员的独有内容追加到 rep.content
        2. 把每个非代表成员的边（单向）迁移到 rep（去重 + 防自环）
        3. 删除非代表成员节点
        4. 建立下行边 node→rep

        合并后 rep 打 hub 标记（extensions={"hub": True}），作为组织中心。
        """
        if rep.id == node.id:
            return

        # 收集非代表成员的独有内容
        merged_parts: list[str] = []
        for m in members:
            if m.id == rep.id:
                continue
            if m.content and m.content != rep.content and m.content not in rep.content:
                merged_parts.append(m.content)

        # 更新 rep 的内容
        if merged_parts:
            new_content = rep.content
            if new_content:
                new_content += "\n" + "\n".join(merged_parts)
            else:
                new_content = "\n".join(merged_parts)
            store.update_node(rep.id, {"content": new_content})

        # 迁移边 + 删除非代表成员
        for m in members:
            if m.id == rep.id:
                continue
            self._migrate_edges(m.id, rep.id, store)
            store.delete_node(m.id)

        # 建立下行边 node→rep
        store.add_edge(node.id, rep.id, type=EDGE_ASSOC)

        logger.info(
            "合并同义：%d 个节点合并到 '%s'（id=%s）",
            len(members) - 1,
            rep.name,
            rep.id,
        )

    def _migrate_edges(
        self, old_id: str, new_id: str, store: StoreInterface
    ) -> None:
        """把 old_id 的所有单向边迁移到 new_id，避免悬空边。

        对于 old_id 的每条边：
        - 如果 new_id 与对端之间已有同 type 边，跳过（不重复）
        - 否则，创建新边（保留 type/priority/extensions），删除旧边
        - 跳过自环
        """
        edges_to_migrate: list[Edge] = []
        for edge in store.get_all_edges():
            if edge.source_id == old_id or edge.target_id == old_id:
                edges_to_migrate.append(edge)

        for edge in edges_to_migrate:
            if edge.source_id == old_id:
                other_id = edge.target_id
                new_source, new_target = new_id, other_id
            else:
                other_id = edge.source_id
                new_source, new_target = other_id, new_id

            # 不迁移自环
            if new_source == new_target:
                continue
            # 去重：同一对端点间同 type 的边只存一份（统一模型无 label；互斥按无序对去重）。
            existing = store.get_edges_between(new_source, new_target)
            if any(e.type == edge.type for e in existing):
                continue

            store.delete_edge(edge.id)
            store.add_edge(
                new_source, new_target,
                type=edge.type, priority=edge.priority,
                extensions=dict(edge.extensions or {}),
            )

    def _validate_reorg(
        self,
        store: StoreInterface,
        rollback_state: dict,
        center_node: Node,
        before_token_total: int | None = None,
    ) -> bool:
        """校验重组后中心节点全邻域 token 总量下降。

        before/after 都按中心节点全邻域（中心 + 全部一跳子节点）同口径估算。
        仅 after < before 才落地，否则回滚。

        Args:
            store: 图存储
            rollback_state: 回滚状态（包含 nodes 和 edges 快照）
            center_node: 中心节点
            before_token_total: 重组前中心节点 + 全部一跳邻域的 token 总量

        Returns:
            True: 校验通过（token 下降）
            False: 校验失败（已回滚）
        """
        if before_token_total is None or self.token_budget is None:
            return True

        # 计算重组后中心节点 + 全部一跳邻域的 token（同口径）
        neighbors = store.get_out_hierarchy(center_node.id)
        after_token_total = self._neighborhood_tokens(center_node, neighbors)

        if after_token_total >= before_token_total:
            logger.warning(
                "重组后中心节点 '%s' 全邻域 token 未下降：before=%d, after=%d，回滚",
                center_node.id, before_token_total, after_token_total,
            )
            self._rollback_reorg(store, rollback_state)
            return False

        return True

    def _rollback_reorg(self, store: StoreInterface, state: dict) -> None:
        """回滚重组：从 ``store.snapshot()`` 快照整体还原。

        委托 ``store.restore`` —— 保留原边 id 并还原变更跟踪集，避免旧实现
        ``add_edge`` 重建（生成新 uuid + 绕过删除跟踪）导致增量持久化残留
        旧行 + 插入新行、边在 DB 翻倍。
        """
        store.restore(state)

    def _create_hub_from_community(
        self,
        community: Any,
        store: StoreInterface,
        neighbors: list[Node],
    ) -> Node | None:
        """从社区信息创建/提拔 hub。

        三种策略：
        - key_concept：提拔现有节点为 hub（打 hub 标记，落 extensions）
        - merge：找到第一个成员作为代表，提拔为 hub
        - summarize：新建概括性 hub
        """
        from mcs.entities.graph import Node as GraphNode

        strategy = getattr(community, "strategy", "summarize")

        if strategy == "key_concept":
            key_id = getattr(community, "key_concept_id", None)
            if key_id and store.get_node(key_id):
                store.update_node(key_id, {"hub": True})
                return store.get_node(key_id)
            # key_id 无效 → 退化为 summarize
            strategy = "summarize"

        if strategy == "merge":
            if not community.member_ids:
                return None
            rep_id = community.member_ids[0]
            if store.get_node(rep_id):
                store.update_node(rep_id, {"hub": True})
                return store.get_node(rep_id)
            return None

        # summarize：新建概括性 hub（概念节点 + hub 标记）
        summary = getattr(community, "summary", None) or getattr(community, "theme", "")
        if not summary:
            return None
        if self._is_overbroad_hub(summary, len(community.member_ids), len(neighbors)):
            return None
        similar = self._find_similar_hub(summary, store)
        if similar:
            return similar
        hub = GraphNode(
            id=str(uuid.uuid4()),
            name=_short_name(summary),
            content=summary,
            node_class=CLASS_CONCEPT,
            extensions={"hub": True},
        )
        store.add_node(hub)
        return hub


def _short_name(summary: str, max_len: int = 40) -> str:
    """取归纳摘要的首行/前若干字符作为中间概念节点的 name。"""
    first = (summary or "").strip().splitlines()
    s = first[0] if first else ""
    return s[:max_len] or "hub"

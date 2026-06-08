"""FanoutReducerPlugin - 压缩邻域超过预算的节点。

对于每个一跳邻居数超过阈值的变更节点，询问 LLM
（``decide_hub`` 目的）哪个邻居应该成为中间枢纽。
Phase 1 通过将邻居的 ``role`` 提升为 ``"hub"`` 来记录选定的枢纽；
完整的图手术（重定向边以形成星型）留待未来完善。
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import replace as dc_replace
from typing import TYPE_CHECKING, Any

from mcs.core.plugin import PluginType
from mcs.interfaces.compaction_plugin import CompactionPluginInterface

if TYPE_CHECKING:
    from collections.abc import Callable

    from mcs.core.graph import Edge, Node
    from mcs.core.plugin_manager import PluginContext
    from mcs.core.store import StoreInterface

logger = logging.getLogger(__name__)

# 持久虚拟根：分层种子图的顶点（固定 id，永不删除）。兜底种子 = 它的(递归)子节点。
SEED_ROOT_ID = "__seed_root__"
SEED_ROOT_NAME = "__seed_root__"

# 过宽 hub 检测的默认阈值
_DEFAULT_MAX_HUB_MEMBER_RATIO = 0.8
_DEFAULT_MAX_HUB_SUMMARY_DOMAINS = 5


class FanoutReducerPlugin(CompactionPluginInterface):
    """当节点的邻域溢出时提升枢纽。

    ``maintain_root=True`` 时，额外维护一个持久虚拟根 ``__seed_root__``：
    把新概念挂到根下，并从根开始递归分层（任一节点扇出超预算就提/建中间 hub 重分配），
    使每层扇出 ≤ 一个上下文窗口、根/hub/层级边落库。
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
        # 单次 decide_hub 的社区规模上限（避免把整语料当一个社区）
        self.max_community_size: int = int(cfg.get("max_community_size", 50))
        # 过宽 hub 检测：成员占比阈值（0-1，超过此比例视为过宽）
        self.max_hub_member_ratio: float = float(
            cfg.get("max_hub_member_ratio", _DEFAULT_MAX_HUB_MEMBER_RATIO)
        )
        # 过宽 hub 检测：摘要中领域关键词上限（简单计数"/"、"、"等分隔符+1）
        self.max_hub_summary_domains: int = int(
            cfg.get("max_hub_summary_domains", _DEFAULT_MAX_HUB_SUMMARY_DOMAINS)
        )

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
        # 无从沿 out 边下钻（曾导致整图扁平、文档级召回为 0）。
        if self.maintain_root and any(
            getattr(n, "role", "concept") == "concept" for n in changed_nodes
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
            if self._exceeds_budget(root, store.get_neighbors(root.id)):
                return True

        # 2. changed_nodes 检查
        for node in changed_nodes:
            if self._exceeds_budget(node, store.get_neighbors(node.id)):
                return True

        # 3. 受影响节点检查（与 changed_nodes 有边的节点）
        changed_ids = {n.id for n in changed_nodes}
        affected_ids: set[str] = set()
        for node in changed_nodes:
            for neighbor in store.get_neighbors(node.id):
                if neighbor.id not in changed_ids:
                    affected_ids.add(neighbor.id)

        for nid in affected_ids:
            node = store.get_node(nid)
            if node is not None:
                if self._exceeds_budget(node, store.get_neighbors(nid)):
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
            for neighbor in store.get_neighbors(node.id):
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
        """对单个节点执行守门 + 裂变，不变量违反时分批循环处理。

        不变量成立时：一次 decide_hub 处理全部邻居；
        不变量违反时：分批处理，每批保证 node + batch ≤ T，循环直到邻域收敛。
        每轮检查邻居数是否下降，无进展则退出防死循环。
        """
        new_hubs: list[Node] = []
        reorgs = 0
        while reorgs < self.max_reorg:
            neighbors = store.get_neighbors(node.id)
            if not self._exceeds_budget(node, neighbors):
                break
            before_neighbor_count = len(neighbors)
            batch = self._select_batch(node, neighbors)
            if len(batch) < 2:
                logger.warning(
                    "节点 '%s' 邻域超预算但剩余邻居 < 2，无法继续聚类",
                    node.name,
                )
                break
            decision, batch = self._decide_hub(node, batch, llm_caller)
            if decision is None:
                break
            batch_hubs = self._reorganize_multi(node, decision, batch, store)
            new_hubs.extend(batch_hubs)
            reorgs += 1
            # 若本批未产出 hub，退出防死循环
            if not batch_hubs:
                break
            # 进展检查：邻居数必须下降
            after_neighbor_count = len(store.get_neighbors(node.id))
            if after_neighbor_count >= before_neighbor_count:
                logger.warning(
                    "节点 '%s' 本轮重组未减少邻居数（%d → %d），退出防死循环",
                    node.name, before_neighbor_count, after_neighbor_count,
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
        """对新 hub 递归守门检查：若新 hub 邻域仍超预算，继续裂变。

        递归深度受 max_reorg 限制，防止 decide_hub 抖动导致失控。
        """
        reorgs = 0
        queue: list[str] = [h.id for h in new_hubs]
        while queue and reorgs < self.max_reorg:
            nid = queue.pop()
            node = store.get_node(nid)
            if node is None:
                continue
            neighbors = store.get_neighbors(nid)
            if not self._exceeds_budget(node, neighbors):
                continue
            batch = self._select_batch(node, neighbors)
            if len(batch) < 2:
                continue
            decision, batch = self._decide_hub(node, batch, llm_caller)
            if decision is None:
                continue
            before = len(store.get_neighbors(nid))
            new_hubs = self._reorganize_multi(node, decision, batch, store)
            reorgs += 1
            for hub in new_hubs:
                queue.append(hub.id)
            if len(store.get_neighbors(nid)) < before:
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

        1) 确保 ``__seed_root__`` 存在；2) 把本次新建的概念挂到根下；
        3) 从根开始递归：任一节点扇出超预算就 ``decide_hub`` 提/建中间 hub、把一批
        子节点重挂到 hub 下，直至每层扇出 ≤ 窗口（或达 max_reorg 上限）；
        4) 把根 + 新增/改动的 hub 追加进 ``changed_nodes``，使写管线阶段 ⑦ 落库。
        """
        from mcs.core.graph import Node

        root = store.get_node(SEED_ROOT_ID)
        if root is None:
            root = Node(
                id=SEED_ROOT_ID, name=SEED_ROOT_NAME, content="", role="hub"
            )
            store.add_node(root)

        # 新概念挂到根下（成为分层种子图的叶子；递归会把它们下推到合适的 hub）
        # 使用有向下行 root→concept（out）
        for n in list(changed_nodes):
            if n.id == root.id:
                continue
            if getattr(n, "role", "concept") == "concept" and store.get_node(n.id):
                store.add_edge(root.id, n.id, direction="out")

        # 递归分层（自根向下；进展检查 + max_reorg 双重防死循环）
        affected: dict[str, Node] = {root.id: root}
        queue: list[str] = [root.id]
        reorgs = 0
        while queue and reorgs < self.max_reorg:
            nid = queue.pop()
            node = store.get_node(nid)
            if node is None:
                continue
            neighbors = store.get_neighbors(nid)
            if not self._exceeds_budget(node, neighbors):
                continue
            batch = self._select_batch(node, neighbors)
            if len(batch) < 2:
                continue
            decision, batch = self._decide_hub(node, batch, llm_caller)
            if decision is None:
                continue
            # 一进多出重组
            before = len(store.get_neighbors(nid))
            new_hubs = self._reorganize_multi(node, decision, batch, store)
            reorgs += 1
            for hub in new_hubs:
                affected[hub.id] = hub
                queue.append(hub.id)  # 新 hub 自身可能超预算 → 继续分层
            if len(store.get_neighbors(nid)) < before:
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
        则把 X 到 M 各成员的直接边替换为单条有向 X → H：减边、减扇出、复用已有 hub。
        包含 root（root 最常需要此优化）。

        净减边判据（重组以降低总量为准）：仅当 ``|M| ≥ 2`` 才吸收——删 |M| 条加 1 条，
        净 -（|M|-1）；|M|<2 无净收益，跳过。

        性能：先一次遍历构建 out 子节点映射，避免每个 (hub, node) 都全表扫边
        （原 O(hubs×nodes×edges)，现 O(edges + hubs×nodes)）。
        """
        # 一次遍历：节点 → out 子节点集合
        out_children: dict[str, set[str]] = {}
        for edge in store.get_all_edges():
            if edge.direction == "out":
                out_children.setdefault(edge.source_id, set()).add(edge.target_id)

        nodes = store.get_all_nodes()
        roles = {n.id: n.role for n in nodes}
        hubs = [n for n in nodes if n.role == "hub"]

        for hub in hubs:
            # hub 的概念成员（out 子节点中非 hub 者，避免层级缠绕）
            hub_members = {
                t for t in out_children.get(hub.id, set())
                if roles.get(t) != "hub"
            }
            # 净减边判据：至少 2 个成员才有收益
            if len(hub_members) < 2:
                continue

            for node in nodes:
                if node.id == hub.id or node.role == "hub":
                    continue  # hub 不吸收其他 hub 的边（避免层级缠绕）
                children = out_children.get(node.id)
                if not children or not hub_members.issubset(children):
                    continue
                # 吸收：删 X→各成员，加 X→hub
                for m_id in hub_members:
                    store.delete_edge(node.id, m_id)
                store.add_edge(node.id, hub.id, direction="out")
                # 同步更新映射，供后续 hub 判定（node 不再直连这些成员，改连 hub）
                children.difference_update(hub_members)
                children.add(hub.id)
                logger.info(
                    "边吸收：节点 %s → hub %s（%d 条边 → 1 条）",
                    node.name, hub.name, len(hub_members),
                )

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
            # 无 token_budget 时用 floor 和邻居数阈值
            if len(neighbors) < self.floor:
                return False
            return len(neighbors) >= 32
        return self._neighborhood_tokens(node, neighbors) > tb.T

    def _select_batch(self, node: Node, neighbors: list[Node]) -> list[Node]:
        """取一跳子节点，保证 node + 返回的子节点渲染量 ≤ 一个上下文窗口，
        且数量 ≤ ``max_community_size``。

        不变量成立时（node + 全部邻居 ≤ T），返回全部邻居（一次验证全部、收敛最快）；
        不变量被违反时（历史遗留超量节点 / 概念渲染极小导致一批装入过多），贪婪选取
        一批——**同时受 token 预算与 max_community_size 双重约束**，避免把上百个概念
        一次性丢给 decide_hub（曾导致 LLM 输出为空、裂变不收敛）。至少 2 个以保证可聚类。
        """
        tb = self.token_budget
        cap = max(2, self.max_community_size)
        if tb is None:
            return neighbors[:min(32, cap)]
        # 不变量成立（全部邻居一次装得下）→ 返回全部（一次 decide_hub 验证全部、收敛最快）。
        # 注：调用方在裂变路径上已先判定超预算，此分支实际只在直接调用 _select_batch 时命中。
        if not self._exceeds_budget(node, neighbors):
            return neighbors
        # 不变量违反：贪婪选取一批（口径与 _exceeds_budget 一致 + 数量封顶）
        logger.warning(
            "节点 '%s' 邻域超预算（%d 个邻居），贪婪选取一批（≤%d）",
            node.name, len(neighbors), cap,
        )
        batch: list[Node] = []
        for nb in neighbors:
            if len(batch) >= cap:
                break
            if batch and self._exceeds_budget(node, [*batch, nb]):
                break
            batch.append(nb)
        # 至少选取 2 个（否则无法聚类）
        if len(batch) < 2 and len(neighbors) >= 2:
            batch = neighbors[:2]
            logger.warning(
                "节点 '%s' 邻域超预算，强制选取前 2 个邻居启动聚类",
                node.name,
            )
        return batch

    def _decide_hub(
        self, node: Node, batch: list[Node], llm_caller: Callable
    ) -> tuple[Any, list[Node]]:
        """调用 decide_hub；空响应 / 解析失败时**折半重试**，返回
        ``(decision, 实际使用的 batch)``；彻底失败返回 ``(None, batch)``。

        批次过大会把模型逼出空响应（实测 deepseek-v4-flash 在 ~200 节点批次上 6/6
        返回空 → 解析失败 → 永不产 hub）。折半重试在 max_community_size 截顶之外再加
        一层鲁棒兜底：先按当前批次试，失败则折半再试，直至成功或批次 ≤ 2。
        """
        current = list(batch)
        for _attempt in range(3):
            try:
                decision = llm_caller(
                    purpose="decide_hub", nodes_in=[node, *current], free_args={}
                )
            except Exception:
                decision = None
            if decision is not None and getattr(decision, "communities", None):
                return decision, current
            if len(current) <= 2:
                break
            current = current[: max(2, len(current) // 2)]  # 折半重试
        return None, current

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
            if node.role != "hub" or node.id == SEED_ROOT_ID:
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
        """有向层级重组：把 ``members`` 从 ``node`` 改挂到 ``hub``，产出有向层级边。

        对原 ``a↔b, a↔c`` 基于 {b,c} 提出 hub ``d`` 时，目标拓扑为：
          下行（父→子）：a→d, d→b, d→c（direction="out"）
          上行（成员回指原父）：b→a, c→a（direction="out"）

        即：不删 a-b/a-c，而是把它们改为有向 b→a / c→a；并新增有向 a→d / d→b / d→c。
        语义边（bidirectional）不受影响。
        """
        if hub.id == node.id:
            return
        for m in members:
            if m.id == hub.id:
                continue
            # 把原双向/无向边 node↔member 改为有向上行 member→node
            store.delete_edge(node.id, m.id)
            store.add_edge(m.id, node.id, direction="out")
            # 新增有向下行 hub→member
            store.add_edge(hub.id, m.id, direction="out")
        # 新增有向下行 node→hub
        store.add_edge(node.id, hub.id, direction="out")

    def _reorganize_multi(
        self,
        node: Node,
        decision: Any,
        neighbors: list[Node],
        store: StoreInterface,
    ) -> list[Node]:
        """一进多出重组：根据 MultiHubDecision 一次造多个 hub。

        Args:
            node: 中心节点（超容量的节点）
            decision: MultiHubDecision（decide_hub.parse 的输出）
            neighbors: 全部一跳子节点
            store: 图存储

        Returns:
            新建的 hub 节点列表
        """
        from mcs.core.decisions import MultiHubDecision
        from mcs.prompts.decide_hub import validate_and_repair

        # 保存回滚状态：深拷贝节点（含 content/role/extensions），使 _merge_synonyms /
        # 提拔 hub 等原地字段改动可被回滚真正还原；边对象不可变，存引用即可。
        rollback_state = {
            "nodes": {
                n.id: dc_replace(n, extensions=dict(n.extensions or {}))
                for n in store.get_all_nodes()
            },
            "edges": list(store.get_all_edges()),
        }

        # 记录重组前的总量
        before_nodes = len(store.get_all_nodes())
        before_edges = len(store.get_all_edges())

        # 计算重组前中心节点 + 一跳邻域的 token 总量
        before_token_total = None
        if self.token_budget is not None:
            before_token_total = self.token_budget.estimate_node(node)
            for nb in neighbors:
                before_token_total += self.token_budget.estimate_node(nb)

        # 仅接受 MultiHubDecision（生产路径 decide_hub.parse 的输出）
        if not isinstance(decision, MultiHubDecision):
            return []

        # 校验 + 修复
        valid_ids = {n.id for n in neighbors}
        decision = validate_and_repair(decision, valid_ids)

        new_hubs: list[Node] = []
        for comm in decision.communities:
            strategy = getattr(comm, "strategy", "summarize")
            hub = self._create_hub_from_community(comm, store, neighbors)
            if hub is None:
                continue
            members = [n for n in neighbors if n.id in comm.member_ids]
            if strategy == "merge":
                # 合并同义：真正合并节点，而非重挂
                self._merge_synonyms(node, hub, members, store)
            else:
                # 重挂：members → hub
                self._reorganize(node, hub, members, store)
            new_hubs.append(hub)

        # unassigned 成员保留在 node 下（确定性兜底，不丢）——它们原本就在 node 下

        # 校验：中心节点扇出应收敛（阻止性）
        if not self._validate_reorg(
            before_nodes, before_edges, store, rollback_state,
            center_node_id=node.id,
            before_token_total=before_token_total,
        ):
            return []  # 校验失败，已回滚

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
        2. 把每个非代表成员的边迁移到 rep（避免悬空边）
        3. 删除非代表成员节点
        4. 建立层级边：node→rep（out）

        合并后 rep.role="hub"，作为组织中心。
        """
        if rep.id == node.id:
            return

        # 收集非代表成员的独有内容
        merged_parts: list[str] = []
        for m in members:
            if m.id == rep.id:
                continue
            # 只追加 rep 中没有的独有内容
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
            # 迁移 m 的所有边到 rep
            self._migrate_edges(m.id, rep.id, store)
            # 删除被合并的节点
            store.delete_node(m.id)

        # 建立层级边：node→rep（out）
        store.add_edge(node.id, rep.id, direction="out")

        logger.info(
            "合并同义：%d 个节点合并到 '%s'（id=%s）",
            len(members) - 1,
            rep.name,
            rep.id,
        )

    def _migrate_edges(
        self, old_id: str, new_id: str, store: StoreInterface
    ) -> None:
        """把 old_id 的所有边迁移到 new_id，避免悬空边。

        对于 old_id 的每条边：
        - 如果 new_id 与对端之间已有边，跳过（不重复）
        - 否则，创建新边（保持原方向），删除旧边
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
            # 如果 new_id 与 other 之间已有同方向边，跳过
            existing = store.get_edge(new_source, new_target)
            if existing is not None and existing.direction == edge.direction:
                continue

            # 删旧边、建新边
            store.delete_edge(edge.source_id, edge.target_id)
            store.add_edge(new_source, new_target, direction=edge.direction)

    def _validate_reorg(
        self,
        before_nodes: int,
        before_edges: int,
        store: StoreInterface,
        rollback_state: dict | None = None,
        center_node_id: str | None = None,
        before_token_total: int | None = None,
    ) -> bool:
        """校验重组后中心节点扇出收敛 + token 总量下降。

        重组将双向边拆为有向边（上行 + 下行），总边数可能增加，这是正常行为。
        核心判据：
        1. 中心节点的扇出（out 边数）应下降，或至少不超过重组前邻域数
        2. 中心节点 + 一跳邻域的 token 总量应下降（优化判据）

        Args:
            before_nodes: 重组前节点数
            before_edges: 重组前边数
            store: 图存储
            rollback_state: 回滚状态（可选，包含 nodes 和 edges 快照）
            center_node_id: 中心节点 id（用于检查扇出收敛）
            before_token_total: 重组前中心节点 + 一跳邻域的 token 总量

        Returns:
            True: 校验通过
            False: 校验失败（若提供 rollback_state 则已回滚）
        """
        after_nodes = len(store.get_all_nodes())

        # 节点数允许小幅增加（新 hub）
        node_increase = after_nodes - before_nodes
        if node_increase > 10:  # 允许最多增加 10 个新 hub
            logger.warning(
                "重组后节点数大幅上升：before=%d, after=%d（增加 %d）",
                before_nodes, after_nodes, node_increase,
            )

        # 核心判据 1：中心节点扇出（out 边数）应下降
        if center_node_id is not None:
            center = store.get_node(center_node_id)
            if center is not None:
                out_count = sum(
                    1 for e in store.get_all_edges()
                    if e.source_id == center_node_id and e.direction == "out"
                )
                # 扇出不应超过重组前的邻居数（不变量保证收敛）
                # 重组前 before_edges 包含双向边，中心节点邻居数 ≤ before_edges
                if out_count > before_edges:
                    logger.error(
                        "重组后中心节点 '%s' 扇出未收敛：out 边数=%d（重组前总边数=%d）",
                        center_node_id, out_count, before_edges,
                    )
                    if rollback_state is not None:
                        self._rollback_reorg(store, rollback_state)
                        logger.info("重组已回滚")
                    return False

        # 核心判据 2：token 总量应下降（优化判据）
        if before_token_total is not None and center_node_id is not None:
            center = store.get_node(center_node_id)
            if center is not None and self.token_budget is not None:
                neighbors = store.get_neighbors(center_node_id)
                after_token_total = self.token_budget.estimate_node(center)
                for nb in neighbors:
                    after_token_total += self.token_budget.estimate_node(nb)
                if after_token_total >= before_token_total:
                    logger.warning(
                        "重组后中心节点 '%s' token 总量未下降：before=%d, after=%d",
                        center_node_id, before_token_total, after_token_total,
                    )
                    # token 未下降是警告而非错误（重组可能增加 hub 但改善结构）
                    # 不触发回滚

        return True

    def _rollback_reorg(self, store: StoreInterface, state: dict) -> None:
        """回滚重组操作。

        Args:
            store: 图存储
            state: 回滚状态，包含 nodes 和 edges 快照
        """
        # 清空当前图
        for n in list(store.get_all_nodes()):
            store._nodes.pop(n.id, None)
            store._adjacency.pop(n.id, None)
        store._edges.clear()

        # 恢复快照
        for n in state["nodes"].values():
            store.add_node(n)
        for e in state["edges"]:
            store.add_edge(e.source_id, e.target_id, direction=e.direction)

    def _create_hub_from_community(
        self,
        community: Any,
        store: StoreInterface,
        neighbors: list[Node],
    ) -> Node | None:
        """从社区信息创建/提拔 hub。

        策略：
        - key_concept：提拔现有节点为 hub
        - merge：找到第一个成员作为代表，提拔为 hub
        - summarize：新建概括性 hub
        """
        from mcs.core.graph import Node as GraphNode

        strategy = getattr(community, "strategy", "summarize")

        if strategy == "key_concept":
            key_id = getattr(community, "key_concept_id", None)
            if key_id and store.get_node(key_id):
                store.update_node(key_id, {"role": "hub"})
                return store.get_node(key_id)
            # key_id 无效 → 退化为 summarize
            strategy = "summarize"

        if strategy == "merge":
            # 合并同义：找第一个成员作为代表
            if not community.member_ids:
                return None
            rep_id = community.member_ids[0]
            if store.get_node(rep_id):
                store.update_node(rep_id, {"role": "hub"})
                return store.get_node(rep_id)
            return None

        # summarize：新建概括性 hub
        summary = getattr(community, "summary", None) or getattr(community, "theme", "")
        if not summary:
            return None
        # 过宽 hub 检测（弱化，但保留基本防护）
        if self._is_overbroad_hub(summary, len(community.member_ids), len(neighbors)):
            return None
        # 去重
        similar = self._find_similar_hub(summary, store)
        if similar:
            return similar
        hub = GraphNode(
            id=str(uuid.uuid4()),
            name=_short_name(summary),
            content=summary,
            role="hub",
        )
        store.add_node(hub)
        return hub


def _short_name(summary: str, max_len: int = 40) -> str:
    """取归纳摘要的首行/前若干字符作为中间概念节点的 name。"""
    first = (summary or "").strip().splitlines()
    s = first[0] if first else ""
    return s[:max_len] or "hub"

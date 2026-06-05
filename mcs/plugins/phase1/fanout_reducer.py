"""FanoutReducerPlugin - 压缩邻域超过预算的节点。

对于每个一跳邻居数超过阈值的变更节点，询问 LLM
（``decide_hub`` 目的）哪个邻居应该成为中间枢纽。
Phase 1 通过将邻居的 ``role`` 提升为 ``"hub"`` 来记录选定的枢纽；
完整的图手术（重定向边以形成星型）留待未来完善。
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING, Any, ClassVar

from mcs.interfaces.compaction_plugin import CompactionPluginInterface
from mcs.plugins.base import Plugin

if TYPE_CHECKING:
    from collections.abc import Callable

    from mcs.core.graph import GraphStore, Node
    from mcs.core.plugin_manager import PluginContext


# 持久虚拟根：分层种子图的顶点（固定 id，永不删除）。兜底种子 = 它的(递归)子节点。
SEED_ROOT_ID = "__seed_root__"
SEED_ROOT_NAME = "__seed_root__"


class FanoutReducerPlugin(Plugin, CompactionPluginInterface):
    """当节点的邻域溢出时提升枢纽。

    ``maintain_root=True``（或 ``MCSConfig.seed_graph_bounding``）时，额外维护一个
    持久虚拟根 ``__seed_root__``：把新概念挂到根下，并从根开始递归分层（任一节点扇出
    超预算就提/建中间 hub 重分配），使每层扇出 ≤ 一个上下文窗口、根/hub/层级边落库。
    """

    name: ClassVar[str] = "fanout_reducer"
    version: ClassVar[str] = "0.1.0"
    interfaces: ClassVar[list[type]] = [CompactionPluginInterface]

    def __init__(self, config: dict | None = None) -> None:
        super().__init__(config)
        cfg = config or {}
        # 邻居数低于 floor 一定不触发（避免极端：节点很大时几个邻居就归纳）
        self.floor: int = cfg.get("floor", 16)
        self.token_budget: Any = None
        # 维护持久虚拟根（分层种子图）；由 MCSConfig.seed_graph_bounding 驱动，默认关
        self.maintain_root: bool = bool(cfg.get("maintain_root", False))
        # 单次 ingest 递归归纳的硬上限，防止 decide_hub 抖动导致失控
        self.max_reorg: int = int(cfg.get("max_reorg", 200))

    def initialize(self, context: PluginContext) -> None:
        self.token_budget = context.token_budget
        cfg = getattr(context, "config", None)
        if cfg is not None and getattr(cfg, "seed_graph_bounding", False):
            self.maintain_root = True

    def shutdown(self) -> None:
        return None

    def should_run(
        self, changed_nodes: list[Node], graph: GraphStore
    ) -> bool:
        if self.maintain_root and changed_nodes:
            return True  # 需把新概念挂到持久根并维护分层
        for node in changed_nodes:
            if self._exceeds_budget(node, graph.get_neighbors(node.id)):
                return True
        return False

    def _exceeds_budget(self, node: Node, neighbors: list[Node]) -> bool:
        """邻域（node + 邻居）渲染 token 累计是否超过上下文窗口（token-aware）。

        邻居数 < floor 一定不触发；无 token_budget 时回退为「邻居 ≥ 32」。
        """
        if len(neighbors) < self.floor:
            return False
        tb = self.token_budget
        if tb is None:
            return len(neighbors) >= 32
        total = tb.estimate(node.content or node.name)
        for nb in neighbors:
            total += tb.estimate(nb.content or nb.name)
            if total > tb.T:
                return True
        return False

    def run(
        self,
        changed_nodes: list[Node],
        graph: GraphStore,
        llm_caller: Callable,
    ) -> None:
        for node in changed_nodes:
            neighbors = graph.get_neighbors(node.id)
            if not self._exceeds_budget(node, neighbors):
                continue
            # 取一批能放进窗口的邻居喂 decide_hub（避免 LLM 输入超限）
            batch = self._select_batch(node, neighbors)
            if len(batch) < 2:
                continue
            try:
                decision = llm_caller(
                    purpose="decide_hub",
                    nodes_in=[node, *batch],
                    free_args={},
                )
            except Exception:
                continue
            if decision is None:
                continue
            hub = self._resolve_hub(decision, graph)
            if hub is not None:
                self._reorganize(node, hub, batch, graph)

        if self.maintain_root:
            self._maintain_seed_root(changed_nodes, graph, llm_caller)

    def _maintain_seed_root(
        self,
        changed_nodes: list[Node],
        graph: GraphStore,
        llm_caller: Callable,
    ) -> None:
        """维护持久虚拟根 + 递归分层种子图。

        1) 确保 ``__seed_root__`` 存在；2) 把本次新建的概念挂到根下；
        3) 从根开始递归：任一节点扇出超预算就 ``decide_hub`` 提/建中间 hub、把一批
        子节点重挂到 hub 下，直至每层扇出 ≤ 窗口（或达 max_reorg 上限）；
        4) 把根 + 新增/改动的 hub 追加进 ``changed_nodes``，使写管线阶段 ⑦ 落库。
        """
        from mcs.core.graph import Node

        root = graph.get_node(SEED_ROOT_ID)
        if root is None:
            root = Node(
                id=SEED_ROOT_ID, name=SEED_ROOT_NAME, content="", role="hub"
            )
            graph.add_node(root)

        # 新概念挂到根下（成为分层种子图的叶子；递归会把它们下推到合适的 hub）
        for n in list(changed_nodes):
            if n.id == root.id:
                continue
            if getattr(n, "role", "concept") == "concept" and graph.get_node(n.id):
                graph.add_edge(root.id, n.id)

        # 递归分层（自根向下；进展检查 + max_reorg 双重防死循环）
        affected: dict[str, Node] = {root.id: root}
        queue: list[str] = [root.id]
        reorgs = 0
        while queue and reorgs < self.max_reorg:
            nid = queue.pop()
            node = graph.get_node(nid)
            if node is None:
                continue
            neighbors = graph.get_neighbors(nid)
            if not self._exceeds_budget(node, neighbors):
                continue
            batch = self._select_batch(node, neighbors)
            if len(batch) < 2:
                continue
            try:
                decision = llm_caller(
                    purpose="decide_hub", nodes_in=[node, *batch], free_args={}
                )
            except Exception:
                continue
            if decision is None:
                continue
            hub = self._resolve_hub(decision, graph)
            if hub is None or hub.id == node.id:
                continue
            before = len(graph.get_neighbors(nid))
            self._reorganize(node, hub, batch, graph)
            reorgs += 1
            affected[hub.id] = hub
            if len(graph.get_neighbors(nid)) < before:
                queue.append(nid)  # 仍可能超预算，继续收敛
            queue.append(hub.id)  # 新 hub 自身可能超预算 → 继续分层

        for nd in affected.values():
            if nd not in changed_nodes:
                changed_nodes.append(nd)

    def _select_batch(self, node: Node, neighbors: list[Node]) -> list[Node]:
        """取一批邻居，使 ``[node, *batch]`` 渲染量 ≤ 窗口，避免 decide_hub 输入超限。

        无 token_budget 时回退取前 32 个。剩余邻居留待后续 compaction 轮处理。
        """
        tb = self.token_budget
        if tb is None:
            return neighbors[:32]
        used = tb.estimate(node.content or node.name)
        batch: list[Node] = []
        for nb in neighbors:
            used += tb.estimate(nb.content or nb.name)
            if used > tb.T and batch:
                break
            batch.append(nb)
        return batch

    def _resolve_hub(self, decision: Any, graph: GraphStore) -> Node | None:
        """从 decide_hub 决策得到中间枢纽：提拔现有节点，或**真正新建**合成节点。"""
        from mcs.core.graph import Node

        hub_id = getattr(decision, "hub_id", None)
        if hub_id and graph.get_node(hub_id) is not None:
            graph.update_node(hub_id, {"role": "hub"})
            return graph.get_node(hub_id)
        summary = getattr(decision, "synthetic_hub_summary", None)
        if summary:
            hub = Node(
                id=str(uuid.uuid4()),
                name=_short_name(summary),
                content=summary,
                role="hub",
            )
            graph.add_node(hub)
            return hub
        return None

    def _reorganize(
        self, node: Node, hub: Node, members: list[Node], graph: GraphStore
    ) -> None:
        """星型重组：把 ``members`` 从 ``node`` 改挂到 ``hub``，``node`` 只连 ``hub``。

        补完「图手术」——把扁平 fanout 收敛成 ``node → hub → members`` 的层次。

        现状：**全双向**，且**删除 node↔member**（只留 node↔hub↔member 星型）。

        TODO(归纳重组的方向与拓扑, 后续做)：改为**有向 + 保留成员到原父的上行边**。
          期望逻辑（社区裁剪）：对 ``a<->b, a<->c`` 基于 {b,c} 提出 hub ``d`` 应得
            下行(父→子)：a→d, d→b, d→c
            上行(成员回指原父)：b→a, c→a
          即：不删 a-b/a-c，而是把它们改为**有向** b→a / c→a；并新增**有向**
          a→d / d→b / d→c。届时需让 _reorganize 支持 direction、navigate/hub_fallback
          按 out 边下钻（见 graph.add_edge(direction="out")）。当前 200 篇 build 用的仍是
          双向星型逻辑，数据拓扑据此理解。
        """
        if hub.id == node.id:
            return
        for m in members:
            if m.id == hub.id:
                continue
            graph.delete_edge(node.id, m.id)
            graph.add_edge(hub.id, m.id)
        graph.add_edge(node.id, hub.id)


def _short_name(summary: str, max_len: int = 40) -> str:
    """取归纳摘要的首行/前若干字符作为中间概念节点的 name。"""
    first = (summary or "").strip().splitlines()
    s = first[0] if first else ""
    return s[:max_len] or "hub"

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


class FanoutReducerPlugin(Plugin, CompactionPluginInterface):
    """当节点的邻域溢出时提升枢纽。"""

    name: ClassVar[str] = "fanout_reducer"
    version: ClassVar[str] = "0.1.0"
    interfaces: ClassVar[list[type]] = [CompactionPluginInterface]

    def __init__(self, config: dict | None = None) -> None:
        super().__init__(config)
        cfg = config or {}
        # 邻居数低于 floor 一定不触发（避免极端：节点很大时几个邻居就归纳）
        self.floor: int = cfg.get("floor", 16)
        self.token_budget: Any = None

    def initialize(self, context: PluginContext) -> None:
        self.token_budget = context.token_budget

    def shutdown(self) -> None:
        return None

    def should_run(
        self, changed_nodes: list[Node], graph: GraphStore
    ) -> bool:
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

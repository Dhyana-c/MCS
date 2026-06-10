"""基于 dict 的内存图存储。

``InMemoryStore`` 是 ``StoreInterface`` 的默认实现，
邻接关系存储为以节点 id 为键的有向字典集合。
持久化钩子（save/load/commit/save_full）为空操作。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from mcs.core.store import StoreInterface

if TYPE_CHECKING:
    from mcs.core.graph import Edge, Node, Subgraph
    from mcs.core.token_budget import TokenBudget


class InMemoryStore(StoreInterface):
    """基于 dict 的内存图存储。

    邻接关系存储为以节点 id 为键的有向字典集合。
    持久化钩子为空操作（不报错，不持久化）。
    """

    def __init__(self) -> None:
        self._nodes: dict[str, Node] = {}
        self._edges: dict[tuple[str, str], Edge] = {}
        self._adjacency: dict[str, set[str]] = {}

    # === 节点 CRUD ===

    def add_node(self, node: Node) -> str:
        self._nodes[node.id] = node
        self._adjacency.setdefault(node.id, set())
        return node.id

    def get_node(self, node_id: str) -> Node | None:
        return self._nodes.get(node_id)

    def update_node(self, node_id: str, updates: dict) -> None:
        node = self._nodes.get(node_id)
        if node is None:
            return
        for key, value in (updates or {}).items():
            if hasattr(node, key):
                setattr(node, key, value)

    def delete_node(self, node_id: str) -> None:
        if node_id not in self._nodes:
            return
        # 删除以该节点为 source 的出边
        for target_id in list(self._adjacency.get(node_id, set())):
            self._edges.pop(self._edge_key(node_id, target_id), None)
        # 删除以该节点为 target 的入边
        for other_id in list(self._adjacency):
            if node_id in self._adjacency[other_id]:
                self._edges.pop(self._edge_key(other_id, node_id), None)
                self._adjacency[other_id].discard(node_id)
        self._adjacency.pop(node_id, None)
        self._nodes.pop(node_id, None)

    # === 边 CRUD ===

    def add_edge(self, source_id: str, target_id: str) -> None:
        if source_id == target_id:
            return
        if source_id not in self._nodes or target_id not in self._nodes:
            return
        key = self._edge_key(source_id, target_id)
        if key in self._edges:
            return
        from mcs.core.graph import Edge

        self._edges[key] = Edge(source_id=source_id, target_id=target_id)
        self._adjacency.setdefault(source_id, set()).add(target_id)

    def get_edge(self, source_id: str, target_id: str) -> Edge | None:
        return self._edges.get(self._edge_key(source_id, target_id))

    def delete_edge(self, source_id: str, target_id: str) -> None:
        self._edges.pop(self._edge_key(source_id, target_id), None)
        self._adjacency.get(source_id, set()).discard(target_id)

    # === 查询 ===

    def get_neighbors(self, node_id: str) -> list[Node]:
        ids = self._adjacency.get(node_id, set())
        return [self._nodes[i] for i in ids if i in self._nodes]

    def get_out_neighbors(self, node_id: str) -> list[Node]:
        return self.get_neighbors(node_id)

    def get_subgraph(
        self, node_id: str, token_budget: TokenBudget | None = None
    ) -> Subgraph:
        from mcs.core.graph import Subgraph

        sub = Subgraph(focus_id=node_id)
        focus = self._nodes.get(node_id)
        if focus is None:
            return sub
        sub.nodes.append(focus)

        if token_budget is None:
            return sub

        used = token_budget.estimate_node(focus)
        visited = {node_id}
        frontier = [node_id]
        while frontier:
            next_frontier: list[str] = []
            for current in frontier:
                for neighbor_id in self._adjacency.get(current, set()):
                    if neighbor_id in visited:
                        continue
                    neighbor = self._nodes.get(neighbor_id)
                    if neighbor is None:
                        continue
                    cost = token_budget.estimate_node(neighbor)
                    if used + cost > token_budget.T:
                        return sub
                    sub.nodes.append(neighbor)
                    used += cost
                    visited.add(neighbor_id)
                    next_frontier.append(neighbor_id)
                    edge = self.get_edge(current, neighbor_id)
                    if edge is not None:
                        sub.edges.append(edge)
            frontier = next_frontier
        return sub

    def get_all_nodes(self) -> list[Node]:
        return list(self._nodes.values())

    def get_all_edges(self) -> list[Edge]:
        return list(self._edges.values())

    # === 内部方法 ===

    @staticmethod
    def _edge_key(source_id: str, target_id: str) -> tuple[str, str]:
        return (source_id, target_id)

"""图存储接口与内存实现。

``GraphStoreInterface`` 是图操作的抽象基类（读写一体化），
``InMemoryGraphStore`` 是基于 dict 的默认实现。
数据类（Node / Edge / Subgraph）定义在 ``graph.py``。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcs.core.graph import Edge, Node, Subgraph
    from mcs.core.token_budget import TokenBudget


class GraphStoreInterface(ABC):
    """图存储抽象基类。

    定义全部图操作方法（节点/边 CRUD + 查询），供消费者依赖。
    具体实现（InMemoryGraphStore、SQLiteGraphStore 等）继承此类。
    """

    # === 节点 CRUD ===

    @abstractmethod
    def add_node(self, node: Node) -> str:
        """添加节点，返回节点 id。"""
        ...

    @abstractmethod
    def get_node(self, node_id: str) -> Node | None:
        """按 id 获取节点，不存在返回 None。"""
        ...

    @abstractmethod
    def update_node(self, node_id: str, updates: dict) -> None:
        """更新节点属性。"""
        ...

    @abstractmethod
    def delete_node(self, node_id: str) -> None:
        """删除节点及其关联边。"""
        ...

    # === 边 CRUD ===

    @abstractmethod
    def add_edge(
        self,
        source_id: str,
        target_id: str,
        direction: str = "bidirectional",
    ) -> None:
        """添加边。direction 为 'bidirectional' 或 'out'。"""
        ...

    @abstractmethod
    def get_edge(self, source_id: str, target_id: str) -> Edge | None:
        """获取两个节点之间的边，不存在返回 None。"""
        ...

    @abstractmethod
    def delete_edge(self, source_id: str, target_id: str) -> None:
        """删除两个节点之间的边。"""
        ...

    # === 查询 ===

    @abstractmethod
    def get_neighbors(self, node_id: str) -> list[Node]:
        """获取全部邻居（bidirectional 两端 + out 边 source 端的 target）。"""
        ...

    @abstractmethod
    def get_out_neighbors(self, node_id: str) -> list[Node]:
        """获取 out 邻居：仅 direction=out 的边目标。"""
        ...

    @abstractmethod
    def get_subgraph(
        self, node_id: str, token_budget: TokenBudget | None = None
    ) -> Subgraph:
        """从焦点节点贪婪 BFS 扩展，在预算耗尽时停止。"""
        ...

    @abstractmethod
    def get_all_nodes(self) -> list[Node]:
        """返回全部节点。"""
        ...

    @abstractmethod
    def get_all_edges(self) -> list[Edge]:
        """返回全部边。"""
        ...


class InMemoryGraphStore(GraphStoreInterface):
    """基于 dict 的内存图存储。

    邻接关系存储为以节点 id 为键的对称字典集合。
    """

    def __init__(self) -> None:
        self._nodes: dict[str, Node] = {}
        self._edges: dict[tuple[str, str, str], Edge] = {}
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
        for other in list(self._adjacency.get(node_id, set())):
            self.delete_edge(node_id, other)
        self._adjacency.pop(node_id, None)
        self._nodes.pop(node_id, None)

    # === 边 CRUD ===

    def add_edge(
        self,
        source_id: str,
        target_id: str,
        direction: str = "bidirectional",
    ) -> None:
        if source_id == target_id:
            return
        if source_id not in self._nodes or target_id not in self._nodes:
            return
        key = self._edge_key(source_id, target_id, direction)
        if key in self._edges:
            return
        from mcs.core.graph import Edge

        self._edges[key] = Edge(
            source_id=source_id, target_id=target_id, direction=direction
        )
        self._adjacency.setdefault(source_id, set()).add(target_id)
        if direction == "bidirectional":
            self._adjacency.setdefault(target_id, set()).add(source_id)

    def get_edge(self, source_id: str, target_id: str) -> Edge | None:
        for direction in ("bidirectional", "out"):
            key = self._edge_key(source_id, target_id, direction)
            edge = self._edges.get(key)
            if edge is not None:
                return edge
        return None

    def delete_edge(self, source_id: str, target_id: str) -> None:
        for direction in ("bidirectional", "out"):
            key = self._edge_key(source_id, target_id, direction)
            self._edges.pop(key, None)
        if self.get_edge(source_id, target_id) is None:
            self._adjacency.get(source_id, set()).discard(target_id)
            self._adjacency.get(target_id, set()).discard(source_id)

    # === 查询 ===

    def get_neighbors(self, node_id: str) -> list[Node]:
        ids = self._adjacency.get(node_id, set())
        return [self._nodes[i] for i in ids if i in self._nodes]

    def get_out_neighbors(self, node_id: str) -> list[Node]:
        result: list[Node] = []
        for edge in self._edges.values():
            if edge.source_id == node_id and edge.direction == "out":
                target = self._nodes.get(edge.target_id)
                if target is not None:
                    result.append(target)
        return result

    def get_subgraph(
        self, node_id: str, token_budget: TokenBudget | None = None
    ) -> Subgraph:
        from mcs.core.graph import Subgraph
        from mcs.core.token_budget import TokenBudget as TB

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
    def _edge_key(
        source_id: str, target_id: str, direction: str
    ) -> tuple[str, str, str]:
        if direction == "bidirectional":
            a, b = (
                (source_id, target_id)
                if source_id < target_id
                else (target_id, source_id)
            )
            return (a, b, "bidirectional")
        return (source_id, target_id, "out")


# 向后兼容别名
GraphStore = InMemoryGraphStore

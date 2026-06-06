"""核心图数据结构和操作。

第一阶段提供内存中的 ``GraphStore``。持久化由 ``SQLiteStoragePlugin`` 单独处理
（针对此内存图进行加载/保存）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Node:
    """概念节点（最小核心）。

    所有变量/场景特定字段（别名、摘要、来源、版本、置信度等）通过 ``extensions`` 字典
    由插件挂载。
    """

    id: str
    name: str
    content: str
    role: str = "concept"  # "concept" | "hub" | "attribute"
    extensions: dict[str, Any] = field(default_factory=dict)


@dataclass
class Edge:
    """无类型邻接边。

    方向来源于社区合并；初始值为"bidirectional"。
    """

    source_id: str
    target_id: str
    direction: str = "bidirectional"  # "bidirectional" | "out"


@dataclass
class Subgraph:
    """以焦点节点为根的子图，受 token 预算限制。"""

    focus_id: str
    nodes: list[Node] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)


class GraphStore:
    """内存图存储。

    邻接关系存储为以节点 id 为键的对称字典集合。``Subgraph`` 通过从焦点节点贪婪扩展邻居构建，
    直到 token 预算耗尽。
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
        # 先删除所有相关联的边
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
            return  # 不允许自环
        if source_id not in self._nodes or target_id not in self._nodes:
            return
        key = self._edge_key(source_id, target_id, direction)
        if key in self._edges:
            return
        self._edges[key] = Edge(
            source_id=source_id, target_id=target_id, direction=direction
        )
        # 邻接关系：bidirectional 两端互为邻居，out 仅 source→target 单向
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
        # 如果这两个节点之间不再有边，则删除邻接关系
        if self.get_edge(source_id, target_id) is None:
            self._adjacency.get(source_id, set()).discard(target_id)
            self._adjacency.get(target_id, set()).discard(source_id)

    # === 查询 ===

    def get_neighbors(self, node_id: str) -> list[Node]:
        """获取全部邻居（bidirectional 边两端互为邻居 + out 边的 source 端也能看到 target）。"""
        ids = self._adjacency.get(node_id, set())
        return [self._nodes[i] for i in ids if i in self._nodes]

    def get_out_neighbors(self, node_id: str) -> list[Node]:
        """获取 out 邻居：仅返回该节点为 source 且 direction=out 的边目标。

        用于层级导航自顶向下下钻（只沿下行边，不沿语义双向边或上行边回退）。
        """
        result: list[Node] = []
        for edge in self._edges.values():
            if edge.source_id == node_id and edge.direction == "out":
                target = self._nodes.get(edge.target_id)
                if target is not None:
                    result.append(target)
        return result

    def get_subgraph(
        self, node_id: str, token_budget: "TokenBudget | None" = None
    ) -> Subgraph:
        """从焦点节点进行贪婪 BFS 扩展，在预算耗尽时停止。

        Args:
            node_id: 焦点节点 id
            token_budget: TokenBudget 实例，用于估算节点渲染量。若为 None，回退为
                只取焦点节点本身（保守行为）。

        估算口径与渲染口径一致：使用 TokenBudget.estimate_node（包含格式行、body、
        extensions）。
        """
        from mcs.core.token_budget import TokenBudget

        sub = Subgraph(focus_id=node_id)
        focus = self._nodes.get(node_id)
        if focus is None:
            return sub
        sub.nodes.append(focus)

        if token_budget is None:
            return sub  # 无预算器时保守返回焦点节点

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
        """规范化边键（含 direction 维度，与 sqlite edges 表主键一致）。

        无向边的端点被规范化，使 (a,b) 和 (b,a) 归一；有向边保持其源-目标顺序。
        键里带上 direction，使同一对节点的有向边 ``a→b`` 与语义双向边 ``a↔b``
        互不覆盖（DB 主键为 ``(source_id, target_id, direction)``，内存与之对齐）。
        """
        if direction == "bidirectional":
            a, b = (
                (source_id, target_id)
                if source_id < target_id
                else (target_id, source_id)
            )
            return (a, b, "bidirectional")
        return (source_id, target_id, "out")

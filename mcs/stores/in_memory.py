"""基于 dict 的内存图存储。

``InMemoryStore`` 是 ``StoreInterface`` 的默认实现，
邻接关系存储为以节点 id 为键的有向字典集合。
持久化钩子（save/load/commit/save_full）为空操作。
"""

from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from mcs.core.store import StoreInterface

if TYPE_CHECKING:
    from mcs.core.token_budget import TokenBudget
    from mcs.entities.graph import Edge, Node, Subgraph


class InMemoryStore(StoreInterface):
    """基于 dict 的内存图存储。

    内部索引：
      - _edges: edge_id -> Edge（主存储）
      - _hierarchy_out: source_id -> set[target_id]（层级出边邻接）
      - _fact_by_node: node_id -> set[edge_id]（事实边两端索引，支持反查）
      - _assoc_by_node: node_id -> set[edge_id]（关联边两端索引，支持反查）
    持久化钩子为空操作（不报错，不持久化）。
    """

    def __init__(self) -> None:
        self._nodes: dict[str, Node] = {}
        self._edges: dict[str, Edge] = {}  # edge_id -> Edge
        self._hierarchy_out: dict[str, set[str]] = {}  # source_id -> {target_id}
        self._fact_by_node: dict[str, set[str]] = {}  # node_id -> {edge_id}
        self._assoc_by_node: dict[str, set[str]] = {}  # node_id -> {edge_id}

    # === 节点 CRUD ===

    def add_node(self, node: Node) -> str:
        self._nodes[node.id] = node
        self._hierarchy_out.setdefault(node.id, set())
        self._fact_by_node.setdefault(node.id, set())
        self._assoc_by_node.setdefault(node.id, set())
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
        # 删除关联边
        edge_ids_to_remove: set[str] = set()
        # 以该节点为 source 的层级出边
        for target_id in list(self._hierarchy_out.get(node_id, set())):
            for e in self._edges.values():
                if (
                    e.source_id == node_id
                    and e.target_id == target_id
                    and e.kind == "hierarchy"
                ):
                    edge_ids_to_remove.add(e.id)
        # 以该节点为端点的事实边
        edge_ids_to_remove |= set(self._fact_by_node.get(node_id, set()))
        # 以该节点为端点的关联边
        edge_ids_to_remove |= set(self._assoc_by_node.get(node_id, set()))
        # 以该节点为 target 的层级入边
        for other_id, targets in self._hierarchy_out.items():
            if node_id in targets and other_id != node_id:
                for e in self._edges.values():
                    if (
                        e.source_id == other_id
                        and e.target_id == node_id
                        and e.kind == "hierarchy"
                    ):
                        edge_ids_to_remove.add(e.id)

        for eid in edge_ids_to_remove:
            self._remove_edge_by_id(eid)
        self._hierarchy_out.pop(node_id, None)
        self._fact_by_node.pop(node_id, None)
        self._assoc_by_node.pop(node_id, None)
        self._nodes.pop(node_id, None)

    # === 边 CRUD ===

    def add_edge(
        self,
        source_id: str,
        target_id: str,
        kind: str = "hierarchy",
        label: str = "",
        priority: float = 0.0,
    ) -> str:
        if source_id == target_id:
            return ""
        if source_id not in self._nodes or target_id not in self._nodes:
            return ""

        from mcs.entities.graph import Edge

        # 层级边去重：同一对节点只允许一条 hierarchy 边
        if kind == "hierarchy":
            for e in self._edges.values():
                if e.source_id == source_id and e.target_id == target_id and e.kind == "hierarchy":
                    return e.id

        # 事实边去重：同一对节点间**同 label** 的事实只存一份（"一条事实只存一份"）。
        # 多篇文档断言同一命题时返回已有边，避免重复事实边累积（频率权重留 Phase 2）。
        # 走 _fact_by_node 索引只扫该端点的事实边，避免全表扫描。
        if kind == "fact":
            for eid in self._fact_by_node.get(source_id, ()):
                e = self._edges.get(eid)
                if (
                    e is not None
                    and e.source_id == source_id
                    and e.target_id == target_id
                    and e.label == label
                ):
                    return e.id

        # 关联边去重：同一对节点 (source, target) 的 assoc 边只存一份（无 label 可区分）。
        if kind == "assoc":
            for eid in self._assoc_by_node.get(source_id, ()):
                e = self._edges.get(eid)
                if (
                    e is not None
                    and e.source_id == source_id
                    and e.target_id == target_id
                    and e.kind == "assoc"
                ):
                    return e.id

        edge = Edge(
            source_id=source_id,
            target_id=target_id,
            id=str(uuid.uuid4()),
            kind=kind,
            label=label,
            priority=priority,
        )
        self._edges[edge.id] = edge

        if kind == "hierarchy":
            self._hierarchy_out.setdefault(source_id, set()).add(target_id)
        elif kind == "fact":
            # fact 边：两端索引
            self._fact_by_node.setdefault(source_id, set()).add(edge.id)
            self._fact_by_node.setdefault(target_id, set()).add(edge.id)
        else:
            # assoc 边：两端索引（与 fact 物理隔离，各自独立索引）
            self._assoc_by_node.setdefault(source_id, set()).add(edge.id)
            self._assoc_by_node.setdefault(target_id, set()).add(edge.id)

        return edge.id

    def delete_edge(self, edge_id_or_source: str, target_id: str | None = None) -> None:
        """按边 id 删除。向后兼容：delete_edge(source, target) 走旧路径。"""
        if target_id is not None:
            # 旧签名 delete_edge(source_id, target_id) — deprecated
            import warnings
            warnings.warn(
                "delete_edge(source, target) is deprecated; use delete_edge(edge_id)",
                DeprecationWarning,
                stacklevel=2,
            )
            for e in self.get_edges_between(edge_id_or_source, target_id):
                if e.kind == "hierarchy":
                    self._remove_edge_by_id(e.id)
                    return
        else:
            self._remove_edge_by_id(edge_id_or_source)

    def update_edge(self, edge_id: str, **fields) -> None:
        edge = self._edges.get(edge_id)
        if edge is None:
            return
        for key, value in fields.items():
            if hasattr(edge, key):
                setattr(edge, key, value)

    # === 层级（骨架）查询 ===

    def get_out_hierarchy(self, node_id: str) -> list[Node]:
        target_ids = self._hierarchy_out.get(node_id, set())
        return [self._nodes[i] for i in target_ids if i in self._nodes]

    # === 事实（双向可达）查询 ===

    def get_facts(self, node_id: str, limit: int | None = None) -> list[Edge]:
        edge_ids = self._fact_by_node.get(node_id, set())
        facts = [self._edges[eid] for eid in edge_ids if eid in self._edges]
        if limit is not None:
            facts = facts[:limit]
        return facts

    def get_out_facts(
        self, node_id: str, limit: int | None = None
    ) -> list[Edge]:
        edge_ids = self._fact_by_node.get(node_id, set())
        out = [
            self._edges[eid]
            for eid in edge_ids
            if eid in self._edges and self._edges[eid].source_id == node_id
        ]
        return out[:limit] if limit is not None else out

    def get_assoc(self, node_id: str, limit: int | None = None) -> list[Edge]:
        edge_ids = self._assoc_by_node.get(node_id, set())
        assoc = [self._edges[eid] for eid in edge_ids if eid in self._edges]
        return assoc[:limit] if limit is not None else assoc

    def get_edges_between(self, source_id: str, target_id: str) -> list[Edge]:
        return [
            e
            for e in self._edges.values()
            if e.source_id == source_id and e.target_id == target_id
        ]

    # === 子图 / 全量查询 ===

    def get_subgraph(
        self, node_id: str, token_budget: TokenBudget | None = None
    ) -> Subgraph:
        from mcs.entities.graph import Subgraph

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
                for neighbor_id in self._hierarchy_out.get(current, set()):
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
                    # 把连接的边加入子图
                    for e in self.get_edges_between(current, neighbor_id):
                        if e.kind == "hierarchy":
                            sub.edges.append(e)
                            break
            frontier = next_frontier
        return sub

    def get_all_nodes(self) -> list[Node]:
        return list(self._nodes.values())

    def get_all_edges(self) -> list[Edge]:
        return list(self._edges.values())

    # === 快照 / 回滚 ===

    def snapshot(self) -> dict:
        """捕获内部图状态快照（供 fanout 回滚）。

        节点用 ``dc_replace`` 拷贝（含 extensions 浅拷贝），使原地字段改动
        （content / role）也能回滚；边拷贝并**保留原 id**；邻接 set 拷贝。
        """
        from dataclasses import replace as dc_replace

        return {
            "nodes": {
                nid: dc_replace(n, extensions=dict(n.extensions or {}))
                for nid, n in self._nodes.items()
            },
            "edges": {eid: dc_replace(e) for eid, e in self._edges.items()},
            "hierarchy_out": {k: set(v) for k, v in self._hierarchy_out.items()},
            "fact_by_node": {k: set(v) for k, v in self._fact_by_node.items()},
            "assoc_by_node": {k: set(v) for k, v in self._assoc_by_node.items()},
        }

    def restore(self, snapshot: dict) -> None:
        """从 ``snapshot()`` 整体还原内部状态（保留边 id）。"""
        self._nodes = dict(snapshot["nodes"])
        self._edges = dict(snapshot["edges"])
        self._hierarchy_out = {
            k: set(v) for k, v in snapshot["hierarchy_out"].items()
        }
        self._fact_by_node = {
            k: set(v) for k, v in snapshot["fact_by_node"].items()
        }
        self._assoc_by_node = {
            k: set(v) for k, v in snapshot.get("assoc_by_node", {}).items()
        }

    # === 内部方法 ===

    def _remove_edge_by_id(self, edge_id: str) -> None:
        edge = self._edges.pop(edge_id, None)
        if edge is None:
            return
        if edge.kind == "hierarchy":
            self._hierarchy_out.get(edge.source_id, set()).discard(edge.target_id)
        elif edge.kind == "fact":
            self._fact_by_node.get(edge.source_id, set()).discard(edge.id)
            self._fact_by_node.get(edge.target_id, set()).discard(edge.id)
        else:  # assoc
            self._assoc_by_node.get(edge.source_id, set()).discard(edge.id)
            self._assoc_by_node.get(edge.target_id, set()).discard(edge.id)

"""基于 dict 的内存图存储（统一图模型）。

``InMemoryStore`` 是 ``StoreInterface`` 的默认实现，
邻接关系存储为以节点 id 为键的有向字典集合。
持久化钩子（save/load/commit/save_full）为空操作。
"""

from __future__ import annotations

import copy
import uuid
import warnings
from dataclasses import replace as dc_replace
from typing import TYPE_CHECKING

from mcs.core.store import StoreInterface
from mcs.entities.graph import (
    ALLOWED_EDGE_TYPES,
    CLASS_EVENT,
    CLASS_FACT,
    CORE_NODE_CLASSES,
    EDGE_ASSOC,
    EDGE_MUTEX,
    Edge,
    Node,
    Subgraph,
    validate_node_class,
)
from mcs.interfaces.priority_scorer import DefaultPriorityScorer

if TYPE_CHECKING:
    from mcs.core.token_budget import TokenBudget


class InMemoryStore(StoreInterface):
    """基于 dict 的内存图存储（统一图模型）。

    内部索引：
      - _edges: edge_id -> Edge（主存储）
      - _assoc_by_node: node_id -> set[edge_id]（关联边两端索引，支持反查 / get_out_hierarchy）
      - _mutex_by_node: node_id -> set[edge_id]（互斥边两端索引，支持反查）
      - _assoc_out: source_id -> set[target_id]（关联出边邻接，驱动 get_out_hierarchy 下钻）
    持久化钩子为空操作（不报错，不持久化）。
    """

    def __init__(self) -> None:
        self._nodes: dict[str, Node] = {}
        self._edges: dict[str, Edge] = {}  # edge_id -> Edge
        self._assoc_by_node: dict[str, set[str]] = {}  # node_id -> {edge_id}（关联，两端）
        self._mutex_by_node: dict[str, set[str]] = {}  # node_id -> {edge_id}（互斥，两端）
        self._assoc_out: dict[str, set[str]] = {}  # source_id -> {target_id}（关联出边）
        self._graph_meta: dict[str, str] = {}  # 图级元数据 kv（非节点字段）
        # 派生优先级打分器（seam，Phase 1 持有但不在 chokepoint 调用，留 Phase 2 接线）
        self._priority_scorer = DefaultPriorityScorer()

    # === 节点 CRUD ===

    def add_node(self, node: Node) -> str:
        validate_node_class(node.node_class)
        self._nodes[node.id] = node
        self._assoc_by_node.setdefault(node.id, set())
        self._mutex_by_node.setdefault(node.id, set())
        self._assoc_out.setdefault(node.id, set())
        return node.id

    def get_node(self, node_id: str) -> Node | None:
        return self._nodes.get(node_id)

    def get_nodes(self, node_ids: list[str]) -> list[Node]:
        result: list[Node] = []
        for nid in node_ids:
            node = self._nodes.get(nid)
            if node is not None:
                result.append(node)
        return result

    def get_nodes_by_class(self, node_class: str) -> list[Node]:
        return [n for n in self._nodes.values() if n.node_class == node_class]

    def update_node(self, node_id: str, updates: dict) -> None:
        node = self._nodes.get(node_id)
        if node is None:
            return
        for key, value in (updates or {}).items():
            if key == "node_class":
                validate_node_class(value)
            if hasattr(node, key):
                setattr(node, key, value)

    def delete_node(self, node_id: str) -> None:
        if node_id not in self._nodes:
            return
        # 删除所有触及该节点的边（关联 + 互斥，任一端）
        edge_ids_to_remove: set[str] = set()
        edge_ids_to_remove |= set(self._assoc_by_node.get(node_id, set()))
        edge_ids_to_remove |= set(self._mutex_by_node.get(node_id, set()))
        # 以该节点为 source 的关联出边对应的边（_assoc_by_node 已含两端，上面已覆盖）
        for eid in edge_ids_to_remove:
            self._remove_edge_by_id(eid)
        self._assoc_by_node.pop(node_id, None)
        self._mutex_by_node.pop(node_id, None)
        self._assoc_out.pop(node_id, None)
        self._nodes.pop(node_id, None)

    # === 边 CRUD ===

    def add_edge(
        self,
        source_id: str,
        target_id: str,
        type: str = EDGE_ASSOC,
        priority: float = 0.0,
        extensions: dict | None = None,
        edge_id: str | None = None,
    ) -> str:
        if type not in ALLOWED_EDGE_TYPES:
            raise ValueError(
                f"unknown edge type={type!r}; expected one of {sorted(ALLOWED_EDGE_TYPES)}"
            )
        if source_id == target_id:
            return ""
        if source_id not in self._nodes or target_id not in self._nodes:
            return ""
        # 宪法：互斥边两端 MUST 均为事实节点（互斥恒为事实↔事实）
        if type == EDGE_MUTEX:
            src = self._nodes.get(source_id)
            tgt = self._nodes.get(target_id)
            if src is not None and src.node_class != CLASS_FACT:
                raise ValueError(
                    f"互斥边 source 节点 {source_id!r} 的 node_class={src.node_class!r}，"
                    f"期望 '{CLASS_FACT}'（互斥仅事实↔事实）"
                )
            if tgt is not None and tgt.node_class != CLASS_FACT:
                raise ValueError(
                    f"互斥边 target 节点 {target_id!r} 的 node_class={tgt.node_class!r}，"
                    f"期望 '{CLASS_FACT}'（互斥仅事实↔事实）"
                )

        existing = self._find_existing_edge(source_id, target_id, type)
        if existing is not None:
            return existing.id

        edge = Edge(
            source_id=source_id,
            target_id=target_id,
            id=edge_id or str(uuid.uuid4()),
            type=type,
            priority=priority,
            extensions=dict(extensions) if extensions else {},
        )
        self._edges[edge.id] = edge

        if type == EDGE_ASSOC:
            # 关联：两端索引 + 出边邻接
            self._assoc_by_node.setdefault(source_id, set()).add(edge.id)
            self._assoc_by_node.setdefault(target_id, set()).add(edge.id)
            self._assoc_out.setdefault(source_id, set()).add(target_id)
        else:  # 互斥：两端索引（无方向语义）
            self._mutex_by_node.setdefault(source_id, set()).add(edge.id)
            self._mutex_by_node.setdefault(target_id, set()).add(edge.id)

        return edge.id

    def _find_existing_edge(
        self, source_id: str, target_id: str, type: str
    ) -> Edge | None:
        """同 (source, target, type) 去重；互斥按无序对 {s,t} 去重。"""
        if type == EDGE_MUTEX:
            for eid in self._mutex_by_node.get(source_id, set()):
                e = self._edges.get(eid)
                if e is not None and {e.source_id, e.target_id} == {source_id, target_id}:
                    return e
            return None
        # 关联：有向 (source, target)
        for eid in self._assoc_by_node.get(source_id, set()):
            e = self._edges.get(eid)
            if (
                e is not None
                and e.source_id == source_id
                and e.target_id == target_id
                and e.type == EDGE_ASSOC
            ):
                return e
        return None

    def delete_edge(self, edge_id_or_source: str, target_id: str | None = None) -> None:
        """按边 id 删除。向后兼容：delete_edge(source, target) 走旧路径。"""
        if target_id is not None:
            # 旧签名 delete_edge(source_id, target_id) — deprecated
            warnings.warn(
                "delete_edge(source, target) is deprecated; use delete_edge(edge_id)",
                DeprecationWarning,
                stacklevel=2,
            )
            for e in self.get_edges_between(edge_id_or_source, target_id):
                if e.type == EDGE_ASSOC:
                    self._remove_edge_by_id(e.id)
                    return
        else:
            self._remove_edge_by_id(edge_id_or_source)

    def update_edge(self, edge_id: str, **fields) -> None:
        edge = self._edges.get(edge_id)
        if edge is None:
            return
        # 登记制 + 互斥两端必为事实（与 add_edge 对称，避免 update 路径绕过校验）
        new_type = fields.get("type", edge.type)
        if new_type not in ALLOWED_EDGE_TYPES:
            raise ValueError(
                f"unknown edge type={new_type!r}; expected one of {sorted(ALLOWED_EDGE_TYPES)}"
            )
        if new_type == EDGE_MUTEX:
            src = self._nodes.get(edge.source_id)
            tgt = self._nodes.get(edge.target_id)
            if src is not None and src.node_class != CLASS_FACT:
                raise ValueError(
                    f"互斥边 source 节点 {edge.source_id!r} 的 node_class={src.node_class!r}，"
                    f"期望 '{CLASS_FACT}'（互斥仅事实↔事实）"
                )
            if tgt is not None and tgt.node_class != CLASS_FACT:
                raise ValueError(
                    f"互斥边 target 节点 {edge.target_id!r} 的 node_class={tgt.node_class!r}，"
                    f"期望 '{CLASS_FACT}'（互斥仅事实↔事实）"
                )
        for key, value in fields.items():
            if hasattr(edge, key):
                setattr(edge, key, value)

    # === 层级（骨架）查询 ===

    def get_out_hierarchy(self, node_id: str) -> list[Node]:
        """下钻成员 = 该节点作 source 的关联出边目标（聚类涌现的组织层级）。"""
        target_ids = self._assoc_out.get(node_id, set())
        return [self._nodes[i] for i in target_ids if i in self._nodes]

    # === 关系（双向可达）查询 ===

    def get_relations(self, node_id: str, limit: int | None = None) -> list[Edge]:
        """该节点作任一端的 关联 / 互斥 边（反查，双向可达）。

        核心节点（概念 / 事实）过滤对端为事件的关联边（载重规则）。
        """
        node = self._nodes.get(node_id)
        if node is None:
            return []
        is_core = node.node_class in CORE_NODE_CLASSES

        edge_ids = self._assoc_by_node.get(node_id, set()) | self._mutex_by_node.get(
            node_id, set()
        )
        result: list[Edge] = []
        for eid in edge_ids:
            edge = self._edges.get(eid)
            if edge is None:
                continue
            # 载重规则：核心节点不反查事件（仅关联边；互斥恒为事实↔事实，不受影响）
            if is_core and edge.type == EDGE_ASSOC:
                other_id = edge.target_id if edge.source_id == node_id else edge.source_id
                other = self._nodes.get(other_id)
                if other is not None and other.node_class == CLASS_EVENT:
                    continue
            result.append(edge)
        if limit is not None:
            result = result[:limit]
        return result

    def get_edges_between(self, source_id: str, target_id: str) -> list[Edge]:
        return [
            e
            for e in self._edges.values()
            if e.source_id == source_id and e.target_id == target_id
        ]

    # === 定向查事件（绕载重规则）===

    def get_related_events(self, node_id: str, limit: int | None = None) -> list[Node]:
        """定向查事件：利用关联边索引高效查找，时间倒排 + limit 截断。

        覆写基类的全量扫描默认实现——InMemoryStore 有 ``_assoc_by_node`` 索引，
        直接从 target 侧查 source 为事件的关联边。
        """
        node = self._nodes.get(node_id)
        if node is None:
            return []
        events: list[Node] = []
        for eid in self._assoc_by_node.get(node_id, set()):
            edge = self._edges.get(eid)
            if edge is None or edge.type != EDGE_ASSOC:
                continue
            # 事件 → node_id（target 侧）
            if edge.target_id == node_id:
                source = self._nodes.get(edge.source_id)
                if source is not None and source.node_class == CLASS_EVENT:
                    events.append(source)
        # 时间倒排
        events.sort(key=lambda n: (n.extensions or {}).get("event_meta", {}).get("timestamp", ""), reverse=True)
        if limit is not None:
            events = events[:limit]
        return events

    # === 子图 / 全量查询 ===

    def get_subgraph(
        self, node_id: str, token_budget: TokenBudget | None = None
    ) -> Subgraph:
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
                for neighbor_id in self._assoc_out.get(current, set()):
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
                    # 把连接的关联边加入子图（一条即可）
                    for e in self.get_edges_between(current, neighbor_id):
                        if e.type == EDGE_ASSOC:
                            sub.edges.append(e)
                            break
            frontier = next_frontier
        return sub

    def get_all_nodes(self) -> list[Node]:
        return list(self._nodes.values())

    def get_all_edges(self) -> list[Edge]:
        return list(self._edges.values())

    # === 图级元数据（非节点字段，不进活跃视图 token 口径）===

    def get_graph_meta(self, key: str) -> str | None:
        return self._graph_meta.get(key)

    def set_graph_meta(self, key: str, value: str) -> None:
        self._graph_meta[key] = value

    # === 快照 / 回滚 ===

    def snapshot(self) -> dict:
        """捕获内部图状态快照（供 fanout 回滚）。

        节点用 ``dc_replace`` 拷贝（含 extensions **深拷贝**），使原地字段改动
        （含嵌套结构，如 alias / source 列表）也能彻底回滚；边拷贝并**保留原 id**；
        邻接 set 拷贝。
        """
        return {
            "nodes": {
                nid: dc_replace(n, extensions=copy.deepcopy(n.extensions or {}))
                for nid, n in self._nodes.items()
            },
            "edges": {
                eid: dc_replace(e, extensions=copy.deepcopy(e.extensions or {}))
                for eid, e in self._edges.items()
            },
            "assoc_by_node": {k: set(v) for k, v in self._assoc_by_node.items()},
            "mutex_by_node": {k: set(v) for k, v in self._mutex_by_node.items()},
            "assoc_out": {k: set(v) for k, v in self._assoc_out.items()},
        }

    def restore(self, snapshot: dict) -> None:
        """从 ``snapshot()`` 整体还原内部状态（保留边 id）。"""
        self._nodes = dict(snapshot["nodes"])
        self._edges = dict(snapshot["edges"])
        self._assoc_by_node = {k: set(v) for k, v in snapshot["assoc_by_node"].items()}
        self._mutex_by_node = {k: set(v) for k, v in snapshot["mutex_by_node"].items()}
        self._assoc_out = {k: set(v) for k, v in snapshot["assoc_out"].items()}

    # === 内部方法 ===

    def _remove_edge_by_id(self, edge_id: str) -> None:
        edge = self._edges.pop(edge_id, None)
        if edge is None:
            return
        if edge.type == EDGE_ASSOC:
            self._assoc_by_node.get(edge.source_id, set()).discard(edge.id)
            self._assoc_by_node.get(edge.target_id, set()).discard(edge.id)
            self._assoc_out.get(edge.source_id, set()).discard(edge.target_id)
        else:  # 互斥
            self._mutex_by_node.get(edge.source_id, set()).discard(edge.id)
            self._mutex_by_node.get(edge.target_id, set()).discard(edge.id)

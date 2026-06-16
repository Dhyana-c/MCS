"""基于 SQLite 的持久化图存储。

``SQLiteStore`` 是 ``StoreInterface`` 的 SQLite 实现，
直接在 SQLite 上做图操作，持久化钩子写入 SQLite 数据库。
不再继承 Plugin，直接实现 StoreInterface。
"""

from __future__ import annotations

import json
import logging
import sqlite3
import uuid
from typing import TYPE_CHECKING, Any

from mcs.core.store import StoreInterface

if TYPE_CHECKING:
    from mcs.core.token_budget import TokenBudget
    from mcs.entities.graph import Edge, Node, Subgraph

logger = logging.getLogger(__name__)

# 存储库 schema 版本（随库持久化，便于未来迁移判别）。
SCHEMA_VERSION = "1"


class StoreProvenanceError(RuntimeError):
    """库出处（``relation_model`` 等）与当前配置不一致，拒绝打开以防混库静默损坏。

    宪法：不同 ``relation_model`` 混库为未定义行为，故 ``relation_model`` 不一致是
    开库唯一的硬拒条件。扩展集变化只告警放行（合法迁移），不抛本异常。
    """


class SQLiteStore(StoreInterface):
    """基于 SQLite 的持久化图存储。

    Phase 1 的图操作仍是内存中的；此存储通过显式的
    ``save()`` / ``load()`` 调用持久化快照。

    内部索引（与 InMemoryStore 同结构）：
      - _edges: edge_id -> Edge（主存储）
      - _hierarchy_out: source_id -> set[target_id]（层级出边邻接）
      - _fact_by_node: node_id -> set[edge_id]（事实边两端索引）
      - _assoc_by_node: node_id -> set[edge_id]（关联边两端索引）

    初始化时需调用 ``initialize()`` 设置数据库连接和可选的
    模式扩展插件列表。
    """

    def __init__(self, config: dict | None = None) -> None:
        self.config = config or {}
        self.path: str = self.config.get("path", ":memory:")
        self.conn: sqlite3.Connection | None = None
        self._schema_extensions: list = []
        # name -> NodeExtensionInterface 插件，用于 extensions 的保真编解码（D5）
        self._node_extensions: dict[str, Any] = {}
        # name -> EdgeExtensionInterface 插件，用于边 extensions 的保真编解码（与节点同构）
        self._edge_extensions: dict[str, Any] = {}
        # 建库出处（relation_model）；开库校验据此拒绝混库。默认 property_graph
        self._relation_model: str = "property_graph"
        # 派生优先级打分器（seam，Phase 1 持有但不在 chokepoint 调用，留 Phase 2 接线）
        self._priority_scorer: Any = None
        # 内存图数据
        self._nodes: dict[str, Node] = {}
        self._edges: dict[str, Edge] = {}  # edge_id -> Edge
        self._hierarchy_out: dict[str, set[str]] = {}  # source_id -> {target_id}
        self._fact_by_node: dict[str, set[str]] = {}  # node_id -> {edge_id}
        self._assoc_by_node: dict[str, set[str]] = {}  # node_id -> {edge_id}（关联边）
        # 增量持久化的变更跟踪
        self._dirty_nodes: set[str] = set()
        self._deleted_nodes: set[str] = set()
        self._dirty_edges: set[str] = set()  # edge_id
        self._deleted_edges: set[str] = set()  # edge_id

    # === 初始化 ===

    def initialize(
        self,
        conn: sqlite3.Connection | None = None,
        schema_extensions: list | None = None,
        node_extensions: dict[str, Any] | None = None,
        edge_extensions: dict[str, Any] | None = None,
        relation_model: str | None = None,
        priority_scorer: Any = None,
    ) -> None:
        """设置数据库连接和模式扩展，并在任何读写前完成出处校验 + 旧库补列。

        ``relation_model`` 不一致 MUST 抛 ``StoreProvenanceError`` 拒绝（防混库）；
        扩展集变化仅告警放行；旧库无出处时按当前配置补写放行；旧库缺
        ``extensions_json`` 列时 ``ALTER TABLE`` 补齐（保证放行后可写）。
        ``priority_scorer`` 为派生优先级 seam（Phase 1 持有但不在 chokepoint 调用）。
        """
        if conn is not None:
            self.conn = conn
        else:
            self.conn = sqlite3.connect(self.path)
        self._schema_extensions = schema_extensions or []
        self._node_extensions = node_extensions or {}
        self._edge_extensions = edge_extensions or {}
        self._relation_model = relation_model or "property_graph"
        if priority_scorer is not None:
            self._priority_scorer = priority_scorer
        elif self._priority_scorer is None:
            from mcs.interfaces.priority_scorer import DefaultPriorityScorer

            self._priority_scorer = DefaultPriorityScorer()
        self._create_tables(self._schema_extensions)
        # 任何读写前：补齐旧库附加列 + 校验 / 补写出处（D5）
        self._ensure_edges_extensions_column()
        self._validate_or_write_provenance()

    def shutdown(self) -> None:
        """关闭数据库连接。"""
        if self.conn is not None:
            self.conn.close()
            self.conn = None

    # === 节点 CRUD ===

    def add_node(self, node: Node) -> str:
        self._nodes[node.id] = node
        self._hierarchy_out.setdefault(node.id, set())
        self._fact_by_node.setdefault(node.id, set())
        self._assoc_by_node.setdefault(node.id, set())
        self._track_node_dirty(node.id)
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
        self._track_node_dirty(node_id)

    def delete_node(self, node_id: str) -> None:
        if node_id not in self._nodes:
            return
        # 收集并删除所有关联边
        edge_ids_to_remove: set[str] = set()
        # 层级出边
        for target_id in list(self._hierarchy_out.get(node_id, set())):
            for e in self._edges.values():
                if (
                    e.source_id == node_id
                    and e.target_id == target_id
                    and e.kind == "hierarchy"
                ):
                    edge_ids_to_remove.add(e.id)
        # 事实边
        edge_ids_to_remove |= set(self._fact_by_node.get(node_id, set()))
        # 关联边
        edge_ids_to_remove |= set(self._assoc_by_node.get(node_id, set()))
        # 层级入边（其他人指向该节点）
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
        self._track_node_deleted(node_id)

    # === 边 CRUD ===

    def add_edge(
        self,
        source_id: str,
        target_id: str,
        kind: str = "hierarchy",
        label: str = "",
        priority: float = 0.0,
        extensions: dict | None = None,
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
            extensions=dict(extensions) if extensions else {},
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

        self._track_edge_dirty(edge.id)
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
        self._track_edge_dirty(edge_id)

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
        """捕获内部图状态 + 变更跟踪集快照（供 fanout 回滚）。

        除节点 / 边 / 邻接外，**MUST 一并捕获 4 个变更跟踪集**：还原它们后，
        下次 ``flush_changes`` 的删 / 增正好抵消本次（被回滚的）reorg，不残留
        旧行、不漏删——否则边会在 DB 里翻倍。边拷贝**保留原 id**。
        """
        from dataclasses import replace as dc_replace

        return {
            "nodes": {
                nid: dc_replace(n, extensions=dict(n.extensions or {}))
                for nid, n in self._nodes.items()
            },
            "edges": {
                eid: dc_replace(e, extensions=dict(e.extensions or {}))
                for eid, e in self._edges.items()
            },
            "hierarchy_out": {k: set(v) for k, v in self._hierarchy_out.items()},
            "fact_by_node": {k: set(v) for k, v in self._fact_by_node.items()},
            "assoc_by_node": {k: set(v) for k, v in self._assoc_by_node.items()},
            "dirty_nodes": set(self._dirty_nodes),
            "deleted_nodes": set(self._deleted_nodes),
            "dirty_edges": set(self._dirty_edges),
            "deleted_edges": set(self._deleted_edges),
        }

    def restore(self, snapshot: dict) -> None:
        """从 ``snapshot()`` 整体还原内部状态 + 变更跟踪集（保留边 id）。"""
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
        self._dirty_nodes = set(snapshot["dirty_nodes"])
        self._deleted_nodes = set(snapshot["deleted_nodes"])
        self._dirty_edges = set(snapshot["dirty_edges"])
        self._deleted_edges = set(snapshot["deleted_edges"])

    # === 持久化钩子 ===

    def save(self) -> None:
        """持久化当前图状态到 SQLite。"""
        if self.conn is None:
            return
        for node in self.get_all_nodes():
            self._save_node(node)
        for edge in self.get_all_edges():
            self._save_edge(edge)
        self.conn.commit()
        self._clear_change_tracking()

    def save_full(self) -> None:
        """全量重建：先清空 nodes/edges 再整图重写，反映边/节点删除。

        只清图表，不动 document_chunks 等辅助表。
        """
        if self.conn is None:
            return
        self.conn.execute("DELETE FROM edges")
        self.conn.execute("DELETE FROM nodes")
        for node in self.get_all_nodes():
            self._save_node(node)
        for edge in self.get_all_edges():
            self._save_edge(edge)
        self.conn.commit()
        self._clear_change_tracking()

    def load(self) -> None:
        """从 SQLite 数据库加载节点和边到内存。"""
        from mcs.entities.graph import Edge, Node

        if self.conn is None:
            return
        for row in self.conn.execute(
            "SELECT id, name, content, role, extensions_json FROM nodes"
        ):
            raw = json.loads(row[4]) if row[4] else {}
            ext = self._deserialize_extensions(raw)
            self._nodes[row[0]] = Node(
                id=row[0], name=row[1], content=row[2] or "", role=row[3], extensions=ext
            )
            self._hierarchy_out.setdefault(row[0], set())
            self._fact_by_node.setdefault(row[0], set())
            self._assoc_by_node.setdefault(row[0], set())

        for row in self.conn.execute(
            "SELECT id, source_id, target_id, kind, label, priority, extensions_json FROM edges"
        ):
            raw = json.loads(row[6]) if row[6] else {}
            ext = self._deserialize_extensions(raw, self._edge_extensions)
            edge = Edge(
                id=row[0],
                source_id=row[1],
                target_id=row[2],
                kind=row[3] or "hierarchy",
                label=row[4] or "",
                priority=row[5] if row[5] is not None else 0.0,
                extensions=ext,
            )
            self._edges[edge.id] = edge
            if edge.kind == "hierarchy":
                self._hierarchy_out.setdefault(edge.source_id, set()).add(edge.target_id)
            elif edge.kind == "fact":
                self._fact_by_node.setdefault(edge.source_id, set()).add(edge.id)
                self._fact_by_node.setdefault(edge.target_id, set()).add(edge.id)
            else:  # assoc
                self._assoc_by_node.setdefault(edge.source_id, set()).add(edge.id)
                self._assoc_by_node.setdefault(edge.target_id, set()).add(edge.id)

        self._clear_change_tracking()

    def commit(self) -> None:
        """提交挂起的写入（供写入管线阶段 ⑦ 调用）。"""
        if self.conn is not None:
            self.conn.commit()

    def mark_node_dirty(self, node_id: str) -> None:
        """显式标记节点为脏，使其在下次 ``flush_changes`` 时被 upsert。"""
        if node_id in self._nodes:
            self._track_node_dirty(node_id)

    def flush_changes(self) -> None:
        """增量落盘自上次 flush/save 以来的节点/边变更（含删除），并提交。"""
        if self.conn is None:
            return
        for eid in self._deleted_edges:
            self.conn.execute("DELETE FROM edges WHERE id=?", (eid,))
        for nid in self._deleted_nodes:
            self.conn.execute("DELETE FROM nodes WHERE id=?", (nid,))
        for nid in self._dirty_nodes:
            node = self._nodes.get(nid)
            if node is not None:
                self._save_node(node)
        for eid in self._dirty_edges:
            edge = self._edges.get(eid)
            if edge is not None:
                self._save_edge(edge)
        self.conn.commit()
        self._clear_change_tracking()

    # === 内部持久化辅助方法 ===

    def _save_node(self, node: Node) -> None:
        if self.conn is None:
            return
        self.conn.execute(
            "INSERT OR REPLACE INTO nodes "
            "(id, name, content, role, extensions_json) VALUES (?, ?, ?, ?, ?)",
            (
                node.id,
                node.name,
                node.content,
                node.role,
                json.dumps(
                    self._serialize_extensions(node.extensions),
                    default=str,
                    ensure_ascii=False,
                ),
            ),
        )

    def _save_edge(self, edge: Edge) -> None:
        if self.conn is None:
            return
        self.conn.execute(
            "INSERT OR REPLACE INTO edges "
            "(id, source_id, target_id, kind, label, priority, extensions_json) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                edge.id,
                edge.source_id,
                edge.target_id,
                edge.kind,
                edge.label,
                edge.priority,
                json.dumps(
                    self._serialize_extensions(
                        edge.extensions, self._edge_extensions
                    ),
                    default=str,
                    ensure_ascii=False,
                ),
            ),
        )

    # === 变更跟踪（增量持久化） ===

    def _track_node_dirty(self, node_id: str) -> None:
        self._dirty_nodes.add(node_id)
        self._deleted_nodes.discard(node_id)

    def _track_node_deleted(self, node_id: str) -> None:
        self._deleted_nodes.add(node_id)
        self._dirty_nodes.discard(node_id)

    def _track_edge_dirty(self, edge_id: str) -> None:
        self._dirty_edges.add(edge_id)
        self._deleted_edges.discard(edge_id)

    def _track_edge_deleted(self, edge_id: str) -> None:
        self._deleted_edges.add(edge_id)
        self._dirty_edges.discard(edge_id)

    def _clear_change_tracking(self) -> None:
        self._dirty_nodes.clear()
        self._deleted_nodes.clear()
        self._dirty_edges.clear()
        self._deleted_edges.clear()

    def _serialize_extensions(
        self, extensions: dict | None, plugin_map: dict[str, Any] | None = None
    ) -> dict:
        """对带编解码的扩展走其 ``serialize()`` 产出 dict。

        ``plugin_map`` 默认 ``self._node_extensions``（节点路径零变化）；
        边扩展传入 ``self._edge_extensions`` 复用同一保真编解码路径。
        """
        plugins = plugin_map if plugin_map is not None else self._node_extensions
        out: dict = {}
        for key, value in (extensions or {}).items():
            ext = plugins.get(key)
            if ext is not None:
                try:
                    out[key] = ext.serialize(value)
                    continue
                except Exception:
                    logger.warning(
                        "serialize(%s) 失败，回退原值", key, exc_info=True
                    )
            out[key] = value
        return out

    def _deserialize_extensions(
        self, raw: dict | None, plugin_map: dict[str, Any] | None = None
    ) -> dict:
        """对带编解码的扩展走其 ``deserialize()`` 还原结构化记录。

        ``plugin_map`` 默认 ``self._node_extensions``；边扩展传入 ``self._edge_extensions``。
        """
        plugins = plugin_map if plugin_map is not None else self._node_extensions
        out: dict = {}
        for key, value in (raw or {}).items():
            ext = plugins.get(key)
            if ext is not None:
                try:
                    out[key] = ext.deserialize(value)
                    continue
                except Exception:
                    logger.warning(
                        "deserialize(%s) 失败，保留原值", key, exc_info=True
                    )
            out[key] = value
        return out

    def _create_tables(self, schema_extensions: list) -> None:
        if self.conn is None:
            return
        base_columns = [
            "id TEXT PRIMARY KEY",
            "name TEXT NOT NULL",
            "content TEXT",
            "role TEXT DEFAULT 'concept'",
            "extensions_json TEXT",
        ]
        ext_columns = []
        for ext in schema_extensions:
            for col, sql_type in (ext.node_columns() or {}).items():
                ext_columns.append(f"{col} {sql_type}")
        nodes_sql = f"CREATE TABLE IF NOT EXISTS nodes ({', '.join(base_columns + ext_columns)})"

        edges_sql = """
            CREATE TABLE IF NOT EXISTS edges (
                id TEXT PRIMARY KEY,
                source_id TEXT NOT NULL,
                target_id TEXT NOT NULL,
                kind TEXT NOT NULL DEFAULT 'hierarchy',
                label TEXT NOT NULL DEFAULT '',
                priority REAL NOT NULL DEFAULT 0.0,
                extensions_json TEXT
            )
        """
        idx_source_sql = "CREATE INDEX IF NOT EXISTS idx_edges_source ON edges(source_id)"
        idx_target_sql = "CREATE INDEX IF NOT EXISTS idx_edges_target ON edges(target_id)"
        meta_sql = """
            CREATE TABLE IF NOT EXISTS meta (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """

        cursor = self.conn.cursor()
        cursor.execute(nodes_sql)
        cursor.execute(edges_sql)
        cursor.execute(idx_source_sql)
        cursor.execute(idx_target_sql)
        cursor.execute(meta_sql)

        for ext in schema_extensions:
            for _name, sql in (ext.auxiliary_tables() or {}).items():
                cursor.executescript(sql)

        self.conn.commit()

    # === 出处（provenance）与旧库补列 ===

    def _ensure_edges_extensions_column(self) -> None:
        """旧库 ``edges`` 表无 ``extensions_json`` 列时补齐（让放行后可写）。

        ``CREATE TABLE IF NOT EXISTS`` 对既存表是 no-op、不会追加新列；故开库 MUST
        显式检测并 ``ALTER TABLE ... ADD COLUMN``（附加列、SQLite 下 O(1)、安全）。
        """
        if self.conn is None:
            return
        cols = {row[1] for row in self.conn.execute("PRAGMA table_info(edges)")}
        if "extensions_json" not in cols:
            self.conn.execute("ALTER TABLE edges ADD COLUMN extensions_json TEXT")
            self.conn.commit()

    def _read_meta_all(self) -> dict[str, str]:
        """读取 ``meta`` 表全部键值；表不存在 / 空返回 ``{}``。"""
        if self.conn is None:
            return {}
        try:
            return {
                row[0]: row[1]
                for row in self.conn.execute("SELECT key, value FROM meta")
            }
        except sqlite3.Error:
            return {}

    def _has_graph_data(self) -> bool:
        """库是否已存有节点 / 边数据（用于区分"真旧库"与"全新空库"）。"""
        if self.conn is None:
            return False
        try:
            n = self.conn.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
            e = self.conn.execute("SELECT COUNT(*) FROM edges").fetchone()[0]
            return (n + e) > 0
        except sqlite3.Error:
            return False

    def _write_provenance(self, relation_model: str, ext_names: list[str]) -> None:
        """写入 / 覆盖出处元信息（``relation_model`` / ``schema_version`` / ``extensions``）。"""
        if self.conn is None:
            return
        self.conn.executemany(
            "INSERT OR REPLACE INTO meta (key, value) VALUES (?, ?)",
            [
                ("relation_model", relation_model),
                ("schema_version", SCHEMA_VERSION),
                ("extensions", json.dumps(ext_names, ensure_ascii=False)),
            ],
        )
        self.conn.commit()

    @staticmethod
    def _parse_ext_set(raw: str | None) -> set[str]:
        """从 meta 的 ``extensions`` 串还原扩展名集合；损坏返回空集。"""
        if not raw:
            return set()
        try:
            val = json.loads(raw)
            return {str(x) for x in val} if isinstance(val, list) else set()
        except (ValueError, TypeError):
            return set()

    def _current_ext_names(self) -> list[str]:
        """当前已挂扩展名集（点 + 边扩展 ``get_name()`` 排序序列化）。"""
        return sorted(set(self._node_extensions) | set(self._edge_extensions))

    def _validate_or_write_provenance(self) -> None:
        """开库出处校验三态（MUST 先于任何读写）。

        - ``relation_model`` 不一致 → 抛 ``StoreProvenanceError`` 拒绝（唯一硬拒）；
        - 出处缺失（旧库 / 空库）→ 按当前配置补写；旧库有数据时记 WARNING 放行；
        - 扩展名集变化 → 记 WARNING、刷新为当前集、放行（合法迁移，新字段取默认）。
        """
        ext_names = self._current_ext_names()
        stored = self._read_meta_all()
        stored_model = stored.get("relation_model")

        if stored_model is None:
            # 旧库无出处（或全新空库）：按当前配置补写；真旧库（有数据）告警
            self._write_provenance(self._relation_model, ext_names)
            if self._has_graph_data():
                logger.warning(
                    "打开无出处元信息的旧库（legacy），已按当前配置 "
                    "relation_model=%s 补写 provenance 放行。",
                    self._relation_model,
                )
            return

        # relation_model 不一致 → 硬拒（防混库静默损坏）
        if stored_model != self._relation_model:
            raise StoreProvenanceError(
                f"库出处 relation_model={stored_model!r} 与当前配置 "
                f"{self._relation_model!r} 不一致；混库为未定义行为，拒绝打开。"
            )

        # 扩展名集变化 → 仅告警、刷新为当前集、放行
        stored_ext = self._parse_ext_set(stored.get("extensions"))
        current_ext = set(ext_names)
        if stored_ext != current_ext:
            logger.warning(
                "库出处扩展集 %s 与当前配置 %s 不一致（合法迁移，新字段取默认、"
                "旧 orphan 字段被忽略），已刷新为当前集并放行。",
                sorted(stored_ext), sorted(current_ext),
            )
            self._write_provenance(self._relation_model, ext_names)

    # === 内部边操作 ===

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
        self._track_edge_deleted(edge_id)

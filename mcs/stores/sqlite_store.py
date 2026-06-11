"""基于 SQLite 的持久化图存储。

``SQLiteStore`` 是 ``StoreInterface`` 的 SQLite 实现，
直接在 SQLite 上做图操作，持久化钩子写入 SQLite 数据库。
不再继承 Plugin，直接实现 StoreInterface。
"""

from __future__ import annotations

import json
import logging
import sqlite3
from typing import TYPE_CHECKING, Any

from mcs.core.store import StoreInterface

if TYPE_CHECKING:
    from mcs.core.graph import Edge, Node, Subgraph
    from mcs.core.token_budget import TokenBudget

logger = logging.getLogger(__name__)


class SQLiteStore(StoreInterface):
    """基于 SQLite 的持久化图存储。

    Phase 1 的图操作仍是内存中的；此存储通过显式的
    ``save()`` / ``load()`` 调用持久化快照。

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
        # 内存图数据（与 InMemoryStore 同结构）
        self._nodes: dict[str, Node] = {}
        self._edges: dict[tuple[str, str], Edge] = {}
        self._adjacency: dict[str, set[str]] = {}
        # 反向邻接表：target_id -> {source_id, ...}，加速 delete_node 入边查找
        self._reverse_adjacency: dict[str, set[str]] = {}
        # 增量持久化的变更跟踪：自上次 flush/save 以来需 upsert / DELETE 的节点与边。
        # 边以 (source_id, target_id) 数据库坐标记录（与 _save_edge 写入一致）。
        self._dirty_nodes: set[str] = set()
        self._deleted_nodes: set[str] = set()
        self._dirty_edges: set[tuple[str, str]] = set()
        self._deleted_edges: set[tuple[str, str]] = set()

    # === 初始化 ===

    def initialize(
        self,
        conn: sqlite3.Connection | None = None,
        schema_extensions: list | None = None,
        node_extensions: dict[str, Any] | None = None,
    ) -> None:
        """设置数据库连接和模式扩展。

        Args:
            conn: SQLite 连接（若未提供则自动连接 self.path）
            schema_extensions: StorageSchemaExtension 插件列表
            node_extensions: name -> NodeExtensionInterface 映射
        """
        if conn is not None:
            self.conn = conn
        else:
            self.conn = sqlite3.connect(self.path)
        self._schema_extensions = schema_extensions or []
        self._node_extensions = node_extensions or {}
        self._create_tables(self._schema_extensions)

    def shutdown(self) -> None:
        """关闭数据库连接。"""
        if self.conn is not None:
            self.conn.close()
            self.conn = None

    # === 节点 CRUD ===

    def add_node(self, node: Node) -> str:
        self._nodes[node.id] = node
        self._adjacency.setdefault(node.id, set())
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
        # 删除以该节点为 source 的出边
        for target_id in list(self._adjacency.get(node_id, set())):
            edge_key = self._edge_key(node_id, target_id)
            edge = self._edges.pop(edge_key, None)
            if edge is not None:
                self._track_edge_deleted(edge)
            self._reverse_adjacency.get(target_id, set()).discard(node_id)
        # 删除以该节点为 target 的入边（使用反向邻接表，O(degree)）
        for source_id in list(self._reverse_adjacency.get(node_id, set())):
            edge_key = self._edge_key(source_id, node_id)
            edge = self._edges.pop(edge_key, None)
            if edge is not None:
                self._track_edge_deleted(edge)
            self._adjacency.get(source_id, set()).discard(node_id)
        self._adjacency.pop(node_id, None)
        self._reverse_adjacency.pop(node_id, None)
        self._nodes.pop(node_id, None)
        self._track_node_deleted(node_id)

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
        self._reverse_adjacency.setdefault(target_id, set()).add(source_id)
        self._track_edge_dirty(self._edges[key])

    def get_edge(self, source_id: str, target_id: str) -> Edge | None:
        return self._edges.get(self._edge_key(source_id, target_id))

    def delete_edge(self, source_id: str, target_id: str) -> None:
        edge = self._edges.pop(self._edge_key(source_id, target_id), None)
        if edge is not None:
            self._track_edge_deleted(edge)
        self._adjacency.get(source_id, set()).discard(target_id)
        self._reverse_adjacency.get(target_id, set()).discard(source_id)

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
        self._clear_change_tracking()  # 内存已全量落盘，跟踪归零

    def save_full(self) -> None:
        """全量重建：先清空 nodes/edges 再整图重写，反映边/节点删除。

        只清图表，不动 document_chunks 等辅助表（idempotency 续跑依赖它）。
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
        self._clear_change_tracking()  # 内存已全量落盘，跟踪归零

    def load(self) -> None:
        """从 SQLite 数据库加载节点和边到内存。"""
        from mcs.core.graph import Node

        if self.conn is None:
            return
        for row in self.conn.execute(
            "SELECT id, name, content, role, extensions_json FROM nodes"
        ):
            raw = json.loads(row[4]) if row[4] else {}
            ext = self._deserialize_extensions(raw)
            self.add_node(
                Node(id=row[0], name=row[1], content=row[2] or "", role=row[3], extensions=ext)
            )
        for row in self.conn.execute(
            "SELECT source_id, target_id FROM edges"
        ):
            self.add_edge(row[0], row[1])
        # 重建反向邻接表（add_edge 已在维护，但显式确认一致性）
        self._rebuild_reverse_adjacency()
        # 加载后内存与 db 一致：清空 add_node/add_edge 期间累积的跟踪，避免首次 flush 冗余重写
        self._clear_change_tracking()

    def commit(self) -> None:
        """提交挂起的写入（供写入管线阶段 ⑦ 调用）。"""
        if self.conn is not None:
            self.conn.commit()

    def mark_node_dirty(self, node_id: str) -> None:
        """显式标记节点为脏，使其在下次 ``flush_changes`` 时被 upsert。

        用于绕过 store 方法的原地改动（如决策阶段对 ``extensions`` 追加 statements /
        别名 / source_tracking），这些改动 store 无从感知，由调用方补标。
        """
        if node_id in self._nodes:
            self._track_node_dirty(node_id)

    def flush_changes(self) -> None:
        """增量落盘自上次 flush/save 以来的节点/边变更（含删除），并提交。

        先执行删除（边、节点）再 upsert，避免「删后又以同 PK 重加」的次序冲突。
        变更由各 add/update/delete 方法跟踪，覆盖决策阶段与压缩/裂变阶段对根、hub、
        层级边的全部增删改——使持久图任意时刻与内存图一致，``save_full`` 不再是
        虚拟根 / 层级边落库的唯一途径（续跑重载即得到完整有根图）。
        """
        if self.conn is None:
            return
        for src, tgt in self._deleted_edges:
            self.conn.execute(
                "DELETE FROM edges WHERE source_id=? AND target_id=?",
                (src, tgt),
            )
        for nid in self._deleted_nodes:
            self.conn.execute("DELETE FROM nodes WHERE id=?", (nid,))
        for nid in self._dirty_nodes:
            node = self._nodes.get(nid)
            if node is not None:
                self._save_node(node)
        for coord in self._dirty_edges:
            edge = self._edges.get(coord)
            # 仅当该坐标的边仍在内存（未被后续删除/改向）时落盘
            if edge is not None and (edge.source_id, edge.target_id) == coord:
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
            "(source_id, target_id) VALUES (?, ?)",
            (edge.source_id, edge.target_id),
        )

    # === 变更跟踪（增量持久化） ===

    def _track_node_dirty(self, node_id: str) -> None:
        self._dirty_nodes.add(node_id)
        self._deleted_nodes.discard(node_id)

    def _track_node_deleted(self, node_id: str) -> None:
        self._deleted_nodes.add(node_id)
        self._dirty_nodes.discard(node_id)

    def _track_edge_dirty(self, edge: Edge) -> None:
        coord = (edge.source_id, edge.target_id)
        self._dirty_edges.add(coord)
        self._deleted_edges.discard(coord)

    def _track_edge_deleted(self, edge: Edge) -> None:
        coord = (edge.source_id, edge.target_id)
        self._deleted_edges.add(coord)
        self._dirty_edges.discard(coord)

    def _clear_change_tracking(self) -> None:
        self._dirty_nodes.clear()
        self._deleted_nodes.clear()
        self._dirty_edges.clear()
        self._deleted_edges.clear()

    def _serialize_extensions(self, extensions: dict | None) -> dict:
        """对带编解码的 NodeExtension 走其 ``serialize()`` 产出 dict（D5）。

        无对应插件的槽位原样保留；``json.dumps(default=str)`` 仅作最后兜底。
        """
        out: dict = {}
        for key, value in (extensions or {}).items():
            ext = self._node_extensions.get(key)
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

    def _deserialize_extensions(self, raw: dict | None) -> dict:
        """对带编解码的 NodeExtension 走其 ``deserialize()`` 还原结构化记录（D5）。

        反序列化失败时保留原始值（不致使 load 整体失败）。
        """
        out: dict = {}
        for key, value in (raw or {}).items():
            ext = self._node_extensions.get(key)
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
                source_id TEXT,
                target_id TEXT,
                PRIMARY KEY (source_id, target_id)
            )
        """
        idx_source_sql = "CREATE INDEX IF NOT EXISTS idx_edges_source ON edges(source_id)"
        idx_target_sql = "CREATE INDEX IF NOT EXISTS idx_edges_target ON edges(target_id)"

        cursor = self.conn.cursor()
        cursor.execute(nodes_sql)
        cursor.execute(edges_sql)
        cursor.execute(idx_source_sql)
        cursor.execute(idx_target_sql)

        for ext in schema_extensions:
            for _name, sql in (ext.auxiliary_tables() or {}).items():
                cursor.executescript(sql)

        self.conn.commit()

    @staticmethod
    def _edge_key(source_id: str, target_id: str) -> tuple[str, str]:
        return (source_id, target_id)

    def _rebuild_reverse_adjacency(self) -> None:
        """从 _adjacency 重建 _reverse_adjacency，确保一致性。"""
        self._reverse_adjacency.clear()
        for source_id, targets in self._adjacency.items():
            for target_id in targets:
                self._reverse_adjacency.setdefault(target_id, set()).add(source_id)

    def add_bidirectional(self, source_id: str, target_id: str) -> None:
        """一次性添加两条单向边 source→target + target→source（语义边）。"""
        self.add_edge(source_id, target_id)
        self.add_edge(target_id, source_id)

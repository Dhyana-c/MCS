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
        self._edges: dict[tuple[str, str, str], Edge] = {}
        self._adjacency: dict[str, set[str]] = {}

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
            "SELECT source_id, target_id, direction FROM edges"
        ):
            # add_edge 已按 direction 如实建边（含同对节点 out + bidirectional 共存）；
            # 旧数据 direction 为 NULL 时回退 bidirectional（与 schema 默认一致）。
            self.add_edge(row[0], row[1], direction=row[2] or "bidirectional")

    def commit(self) -> None:
        """提交挂起的写入（供写入管线阶段 ⑦ 调用）。"""
        if self.conn is not None:
            self.conn.commit()

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
            "(source_id, target_id, direction) VALUES (?, ?, ?)",
            (edge.source_id, edge.target_id, edge.direction),
        )

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
                direction TEXT DEFAULT 'bidirectional',
                PRIMARY KEY (source_id, target_id, direction)
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
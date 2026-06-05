"""SQLiteStoragePlugin - 具有动态模式扩展的持久化。

实现 ``StorageInterface``。初始化时，通过插件管理器收集所有
``StorageSchemaExtensionInterface`` 插件，并动态构建 ``nodes``
表模式（基础列 + 扩展列）以及辅助表。
"""

from __future__ import annotations

import json
import logging
import sqlite3
from typing import TYPE_CHECKING, Any, ClassVar

from mcs.interfaces.storage import StorageInterface
from mcs.plugins.base import Plugin

if TYPE_CHECKING:
    from mcs.core.graph import Edge, GraphStore, Node
    from mcs.core.plugin_manager import PluginContext

logger = logging.getLogger(__name__)


class SQLiteStoragePlugin(Plugin, StorageInterface):
    """具有动态模式扩展的 SQLite 持久化。

    注意：Phase 1 的图操作是内存中的；此插件通过显式的
    ``save()`` / ``load()`` 调用持久化快照。每次变更后自动
    刷新留待未来实现。
    """

    name: ClassVar[str] = "sqlite_storage"
    version: ClassVar[str] = "0.1.0"
    interfaces: ClassVar[list[type]] = [StorageInterface]

    def __init__(self, config: dict | None = None) -> None:
        super().__init__(config)
        self.path: str = self.config.get("path", ":memory:")
        self.conn: sqlite3.Connection | None = None
        self._schema_extensions: list = []
        # name -> NodeExtensionInterface 插件，用于 extensions 的保真编解码（D5）
        self._node_extensions: dict[str, Any] = {}

    # === 插件 / StorageInterface 生命周期 ===

    def initialize(self, context: PluginContext) -> None:
        self.conn = sqlite3.connect(self.path)
        self._schema_extensions = context.plugin_manager.collect_schema_extensions()
        self._node_extensions = {
            ext.name: ext
            for ext in context.plugin_manager.collect_node_extensions()
        }
        self._create_tables(self._schema_extensions)

    def shutdown(self) -> None:
        if self.conn is not None:
            self.conn.close()
            self.conn = None

    # === StorageInterface ===

    def save(self, graph: GraphStore) -> None:
        if self.conn is None:
            return
        for node in graph.get_all_nodes():
            self.save_node(node)
        for edge in graph.get_all_edges():
            self.save_edge(edge)
        self.conn.commit()

    def save_full(self, graph: GraphStore) -> None:
        """全量重建：先清空 nodes/edges 再整图重写，反映边/节点删除（如分层归纳重挂）。

        只清图表，不动 document_chunks 等辅助表（idempotency 续跑依赖它）。
        """
        if self.conn is None:
            return
        self.conn.execute("DELETE FROM edges")
        self.conn.execute("DELETE FROM nodes")
        for node in graph.get_all_nodes():
            self.save_node(node)
        for edge in graph.get_all_edges():
            self.save_edge(edge)
        self.conn.commit()

    def load(self) -> GraphStore:
        from mcs.core.graph import GraphStore, Node

        graph = GraphStore()
        if self.conn is None:
            return graph
        for row in self.conn.execute(
            "SELECT id, name, content, role, extensions_json FROM nodes"
        ):
            raw = json.loads(row[4]) if row[4] else {}
            ext = self._deserialize_extensions(raw)
            graph.add_node(
                Node(id=row[0], name=row[1], content=row[2] or "", role=row[3], extensions=ext)
            )
        for row in self.conn.execute(
            "SELECT source_id, target_id, direction FROM edges"
        ):
            graph.add_edge(row[0], row[1], direction=row[2])
            # 如有必要，恢复存储边上的方向。
            edge = graph.get_edge(row[0], row[1])
            if edge is not None and row[2] in ("bidirectional", "out"):
                edge.direction = row[2]
        return graph

    def save_node(self, node: Node) -> None:
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

    def commit(self) -> None:
        """提交挂起的写入（StorageInterface 的可选钩子；供写入管线阶段 ⑦ 调用）。"""
        if self.conn is not None:
            self.conn.commit()

    def save_edge(self, edge: Edge) -> None:
        if self.conn is None:
            return
        self.conn.execute(
            "INSERT OR REPLACE INTO edges "
            "(source_id, target_id, direction) VALUES (?, ?, ?)",
            (edge.source_id, edge.target_id, edge.direction),
        )

    # === 内部方法 ===

    def _serialize_extensions(self, extensions: dict | None) -> dict:
        """对带编解码的 NodeExtension 走其 ``serialize()`` 产出 dict（D5）。

        无对应插件的槽位原样保留（如 alias_index/statements/summary 本就可 JSON 序列化）；
        ``json.dumps(default=str)`` 仅作最后兜底，避免意外类型导致整次落盘失败。
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


_ = Any  # 消除未使用导入的 lint 警告

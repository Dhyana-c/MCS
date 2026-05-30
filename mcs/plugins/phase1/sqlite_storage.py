"""SQLiteStoragePlugin - persistence with dynamic schema extensions.

Implements ``StorageInterface``. On initialize, collects all
``StorageSchemaExtensionInterface`` plugins via the plugin manager and
dynamically builds the ``nodes`` table schema (base columns + extension
columns) plus auxiliary tables.
"""

from __future__ import annotations

import json
import sqlite3
from typing import TYPE_CHECKING, Any, ClassVar

from mcs.interfaces.storage import StorageInterface
from mcs.plugins.base import Plugin

if TYPE_CHECKING:
    from mcs.core.graph import Edge, GraphStore, Node
    from mcs.core.plugin_manager import PluginContext


class SQLiteStoragePlugin(Plugin, StorageInterface):
    """SQLite persistence with dynamic schema extensions.

    Note: Phase 1 graph operations are in-memory; this plugin persists
    snapshots via explicit ``save()`` / ``load()`` calls. Auto-flushing
    on every change is deferred to future work.
    """

    name: ClassVar[str] = "sqlite_storage"
    version: ClassVar[str] = "0.1.0"
    interfaces: ClassVar[list[type]] = [StorageInterface]

    def __init__(self, config: dict | None = None) -> None:
        super().__init__(config)
        self.path: str = self.config.get("path", ":memory:")
        self.conn: sqlite3.Connection | None = None
        self._schema_extensions: list = []

    # === Plugin / StorageInterface lifecycle ===

    def initialize(self, context: PluginContext) -> None:
        self.conn = sqlite3.connect(self.path)
        self._schema_extensions = context.plugin_manager.collect_schema_extensions()
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

    def load(self) -> GraphStore:
        from mcs.core.graph import GraphStore, Node

        graph = GraphStore()
        if self.conn is None:
            return graph
        for row in self.conn.execute(
            "SELECT id, name, content, role, extensions_json FROM nodes"
        ):
            ext = json.loads(row[4]) if row[4] else {}
            graph.add_node(
                Node(id=row[0], name=row[1], content=row[2] or "", role=row[3], extensions=ext)
            )
        for row in self.conn.execute(
            "SELECT source_id, target_id, direction FROM edges"
        ):
            graph.add_edge(row[0], row[1], direction=row[2])
            # Restore the direction on the stored edge if necessary.
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
                json.dumps(node.extensions, default=str, ensure_ascii=False),
            ),
        )

    def save_edge(self, edge: Edge) -> None:
        if self.conn is None:
            return
        self.conn.execute(
            "INSERT OR REPLACE INTO edges "
            "(source_id, target_id, direction) VALUES (?, ?, ?)",
            (edge.source_id, edge.target_id, edge.direction),
        )

    # === Internal ===

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


_ = Any  # silence unused-import lint

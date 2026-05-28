"""SQLiteStoragePlugin - SQLite persistence with dynamic schema extensions.

Implements ``StorageInterface``. On initialize, collects all
``StorageSchemaExtensionInterface`` plugins via the plugin manager and
dynamically builds the ``nodes`` table schema (base columns + extension
columns) plus any auxiliary tables.

See architecture.md §6.4.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

from mcs.interfaces.storage import StorageInterface
from mcs.plugins.base import Plugin

if TYPE_CHECKING:
    from mcs.core.graph import Edge, GraphStore, Node
    from mcs.core.plugin_manager import PluginContext


class SQLiteStoragePlugin(Plugin, StorageInterface):
    """SQLite persistence with dynamic schema extensions.

    Phase 1 implementation pending. See architecture.md §6.4.
    """

    name: ClassVar[str] = "sqlite_storage"
    version: ClassVar[str] = "0.1.0"
    interfaces: ClassVar[list[type]] = [StorageInterface]

    def __init__(self, config: dict | None = None) -> None:
        super().__init__(config)
        self.path: str = self.config.get("path", "mcs.db")
        self.conn: Any = None

    # === Plugin / StorageInterface lifecycle (single initialize satisfies both) ===

    def initialize(self, context: PluginContext) -> None:
        raise NotImplementedError("Phase 1 implementation pending")

    def shutdown(self) -> None:
        raise NotImplementedError("Phase 1 implementation pending")

    # === StorageInterface ===

    def save(self, graph: GraphStore) -> None:
        raise NotImplementedError("Phase 1 implementation pending")

    def load(self) -> GraphStore:
        raise NotImplementedError("Phase 1 implementation pending")

    def save_node(self, node: Node) -> None:
        raise NotImplementedError("Phase 1 implementation pending")

    def save_edge(self, edge: Edge) -> None:
        raise NotImplementedError("Phase 1 implementation pending")

    # === Internal ===

    def _create_tables(self, schema_extensions: list) -> None:
        """Build ``nodes`` table with base + extension columns; create aux tables."""
        raise NotImplementedError("Phase 1 implementation pending")

"""Storage interface - abstract base for graph persistence backends."""

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcs.core.graph import Edge, GraphStore, Node
    from mcs.core.plugin_manager import PluginContext


class StorageInterface(ABC):
    """Abstract storage backend.

    Implementations persist nodes and edges to durable storage.
    See architecture.md §3.1.
    """

    @abstractmethod
    def initialize(self, context: "PluginContext") -> None:
        """Initialize storage.

        Implementations should call
        ``context.plugin_manager.collect_schema_extensions()`` to dynamically
        build their schema (columns + auxiliary tables).

        NOTE: This shares its signature with ``Plugin.initialize()`` so that
        multi-inheritance subclasses (Plugin + StorageInterface) define a
        single concrete ``initialize`` method that satisfies both. This
        slightly deviates from architecture.md §3.1 which shows the old
        signature ``initialize(schema_extensions)``.
        """
        pass

    @abstractmethod
    def save(self, graph: "GraphStore") -> None:
        """Persist the whole graph (cold snapshot)."""
        pass

    @abstractmethod
    def load(self) -> "GraphStore":
        """Load the graph from storage."""
        pass

    @abstractmethod
    def save_node(self, node: "Node") -> None:
        """Persist a single node."""
        pass

    @abstractmethod
    def save_edge(self, edge: "Edge") -> None:
        """Persist a single edge."""
        pass

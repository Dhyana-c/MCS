"""Index interface - lexical lookup for seed location."""

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcs.core.graph import GraphStore, Node


class IndexInterface(ABC):
    """Abstract index backend.

    Provides query-string -> node-id lookups for seed location.
    See architecture.md §3.2.
    """

    @abstractmethod
    def build(self, graph: "GraphStore") -> None:
        """Build the index from an existing graph."""
        pass

    @abstractmethod
    def lookup(self, query: str) -> list[str]:
        """Return matching node IDs for the query string."""
        pass

    @abstractmethod
    def add_entry(self, node: "Node") -> None:
        """Add a node to the index."""
        pass

    @abstractmethod
    def remove_entry(self, node_id: str) -> None:
        """Remove a node from the index."""
        pass

    @abstractmethod
    def update_entry(self, node: "Node") -> None:
        """Update a node's index entry."""
        pass

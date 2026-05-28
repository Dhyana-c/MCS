"""Maintenance interface - background tasks like GC."""

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcs.core.graph import GraphStore


class MaintenanceInterface(ABC):
    """Abstract maintenance task.

    Phase 2 GC and other periodic tasks. See architecture.md §3.8.
    """

    @abstractmethod
    def run(self, graph: "GraphStore") -> None:
        """Execute the maintenance task."""
        pass

    @abstractmethod
    def should_run(self) -> bool:
        """Decide whether to run now (e.g., based on time elapsed)."""
        pass

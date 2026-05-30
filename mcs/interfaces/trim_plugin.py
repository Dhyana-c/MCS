"""Trim plugin interface - reduce node lists to fit a token budget.

See openspec/specs/plugin-protocol/spec.md "TrimPluginInterface".
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcs.core.graph import Node


class TrimPluginInterface(ABC):
    """Reduce a list of nodes so their estimated token count fits ``budget``.

    Used at:
      - Query stage ② seed trimming (after entry-plugin merge)
      - Query stage ④ as the underlying mechanism of a PriorityArbitration

    Trim implementations MUST preserve the input order of nodes (they
    represent priority); they MUST NOT reorder.
    """

    @abstractmethod
    def trim(self, nodes: list[Node], budget: int) -> list[Node]:
        """Return a subset of ``nodes`` whose total estimated tokens ≤ budget."""
        pass

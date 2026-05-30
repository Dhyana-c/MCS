"""Entry plugin interface - seed location at query stage ②.

See openspec/specs/plugin-protocol/spec.md "EntryPluginInterface".
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, ClassVar

if TYPE_CHECKING:
    from mcs.core.graph import Node


class EntryPluginInterface(ABC):
    """Locate seed nodes for the query pipeline.

    Subclasses set ``priority`` (higher first) and may set ``exclusive=True``
    to short-circuit lower-priority plugins on non-empty hit.

    The query pipeline executes all registered EntryPlugins in priority
    order. Their outputs are merged (priority-sorted) and trimmed to fit
    ``token_budget.T`` before entering stage ③ semantic loop.
    """

    priority: ClassVar[int] = 0
    exclusive: ClassVar[bool] = False

    @abstractmethod
    def locate(self, query: str, ctx: Any) -> list[Node]:
        """Return candidate seed nodes for ``query``.

        ``ctx`` is the QueryContext. Returning an empty list means this
        plugin found nothing — the chain continues to lower-priority plugins.
        """
        pass

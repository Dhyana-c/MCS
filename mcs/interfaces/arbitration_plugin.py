"""Arbitration plugin interface - query stage ④ result selection.

See openspec/specs/plugin-protocol/spec.md "ArbitrationPluginInterface".
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mcs.core.graph import Node


class ArbitrationPluginInterface(ABC):
    """Select the final result set from ``accumulated``.

    Single-responsibility: ``List[Node] -> List[Node]``. At most one
    ArbitrationPlugin can be registered per pipeline configuration.

    Examples: PriorityArbitration (hard truncate by priority), LLMArbitration
    (let an LLM resolve conflicts between versions).
    """

    @abstractmethod
    def arbitrate(
        self,
        accumulated: list[Node],
        query: str,
        ctx: Any,
    ) -> list[Node]:
        """Return the final result set from accumulated nodes.

        Output MUST be ``List[Node]``; this stage MUST NOT change node
        content or produce non-Node outputs.
        """
        pass

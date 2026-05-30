"""PriorityTrimPlugin - default trim implementation.

Iterates nodes in input order (which represents priority), accumulates
token estimates, and stops at the first node that would exceed the
budget.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from mcs.interfaces.trim_plugin import TrimPluginInterface
from mcs.plugins.base import Plugin

if TYPE_CHECKING:
    from mcs.core.graph import Node
    from mcs.core.plugin_manager import PluginContext
    from mcs.core.token_budget import TokenBudget


class PriorityTrimPlugin(Plugin, TrimPluginInterface):
    """Keep nodes in priority order, drop the tail that overflows budget."""

    name: ClassVar[str] = "priority_trim"
    version: ClassVar[str] = "0.1.0"
    interfaces: ClassVar[list[type]] = [TrimPluginInterface]

    def __init__(self, config: dict | None = None) -> None:
        super().__init__(config)
        self.token_budget: TokenBudget | None = None

    def initialize(self, context: PluginContext) -> None:
        self.token_budget = context.token_budget

    def shutdown(self) -> None:
        self.token_budget = None

    def trim(self, nodes: list[Node], budget: int) -> list[Node]:
        if not nodes:
            return []
        result: list[Node] = []
        used = 0
        for node in nodes:
            cost = self._estimate(node)
            if result and used + cost > budget:
                break
            result.append(node)
            used += cost
        return result

    def _estimate(self, node: Node) -> int:
        if self.token_budget is not None:
            return self.token_budget.estimate(node.content or node.name)
        # Fallback if not initialized.
        text = node.content or node.name or ""
        return max(1, len(text) // 2)

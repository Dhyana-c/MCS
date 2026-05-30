"""HubFallbackEntryPlugin - lowest-priority entry plugin.

Used when higher-priority entry plugins (e.g. AliasEntry) return empty
results. Returns hub-role nodes as initial seeds so the semantic loop
can drill down from there.

The full top-down LLM navigation described in MCS技术方案.md §5.1 (using
``navigate_hub`` purpose) is the natural extension; Phase 1 ships the
simpler hub-collection behavior and leaves LLM navigation for future
refinement.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

from mcs.interfaces.entry_plugin import EntryPluginInterface
from mcs.plugins.base import Plugin

if TYPE_CHECKING:
    from mcs.core.graph import GraphStore, Node
    from mcs.core.plugin_manager import PluginContext


class HubFallbackEntryPlugin(Plugin, EntryPluginInterface):
    """Return hub-role nodes (or empty if there are none)."""

    name: ClassVar[str] = "hub_fallback"
    version: ClassVar[str] = "0.1.0"
    interfaces: ClassVar[list[type]] = [EntryPluginInterface]
    priority: ClassVar[int] = 0
    exclusive: ClassVar[bool] = False

    def __init__(self, config: dict | None = None) -> None:
        super().__init__(config)
        self.graph: GraphStore | None = None
        self.max_seeds: int = (config or {}).get("max_seeds", 10)

    def initialize(self, context: PluginContext) -> None:
        self.graph = context.graph

    def shutdown(self) -> None:
        self.graph = None

    def locate(self, query: str, ctx: Any) -> list[Node]:
        if self.graph is None:
            return []
        hubs = [n for n in self.graph.get_all_nodes() if n.role == "hub"]
        if not hubs:
            return []
        return hubs[: self.max_seeds]

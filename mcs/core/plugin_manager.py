"""Plugin manager - register, lookup, and lifecycle-manage plugins.

Supports the 5 new plugin interfaces defined in
openspec/specs/plugin-protocol/spec.md:

  - EntryPluginInterface       (priority-sorted on get_all)
  - TrimPluginInterface
  - ArbitrationPluginInterface (singleton-enforced)
  - PostprocessPluginInterface
  - CompactionPluginInterface

Plus the existing interfaces (Storage / Index / LLM / NodeExtension /
StorageSchemaExtension / Maintenance).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from mcs.core.errors import ConfigurationError

if TYPE_CHECKING:
    from mcs.core.config import MCSConfig
    from mcs.core.context_renderer import ContextRenderer
    from mcs.core.graph import GraphStore
    from mcs.core.token_budget import TokenBudget
    from mcs.interfaces.node_extension import NodeExtensionInterface
    from mcs.interfaces.storage_schema_ext import StorageSchemaExtensionInterface
    from mcs.plugins.base import Plugin


@dataclass
class PluginContext:
    """Runtime context injected into ``Plugin.initialize()``.

    Plugins use this to access core engine objects and discover peers.
    """

    graph: GraphStore
    config: MCSConfig
    token_budget: TokenBudget
    context_renderer: ContextRenderer
    plugin_manager: PluginManager


class PluginManager:
    """Register, lookup, and lifecycle-manage plugins."""

    def __init__(self) -> None:
        self.plugins: dict[str, Plugin] = {}
        self.interfaces: dict[type, list[Plugin]] = {}

    def register(self, plugin: Plugin) -> None:
        """Register a plugin and index it by all interfaces it implements.

        Raises ``ConfigurationError`` if registering this plugin would
        violate a singleton constraint (e.g. a second ArbitrationPlugin).
        """
        from mcs.interfaces.arbitration_plugin import ArbitrationPluginInterface

        if ArbitrationPluginInterface in plugin.interfaces:
            existing = self.interfaces.get(ArbitrationPluginInterface, [])
            if existing:
                raise ConfigurationError(
                    "At most one ArbitrationPlugin may be registered per "
                    f"configuration; already have {existing[0].name!r}, "
                    f"refusing to add {plugin.name!r}"
                )

        self.plugins[plugin.name] = plugin
        for iface in plugin.interfaces:
            self.interfaces.setdefault(iface, []).append(plugin)

    def get(self, interface: type) -> Plugin | None:
        """Return the first plugin implementing the interface, or None."""
        plugins = self.get_all(interface)
        return plugins[0] if plugins else None

    def get_all(self, interface: type) -> list[Plugin]:
        """Return all plugins implementing the interface.

        For ``EntryPluginInterface``, the returned list is sorted by
        ``priority`` descending (highest first). Ties keep registration
        order (Python's sorted is stable).
        """
        from mcs.interfaces.entry_plugin import EntryPluginInterface

        plugins = list(self.interfaces.get(interface, []))
        if interface is EntryPluginInterface:
            plugins.sort(key=lambda p: -p.priority)
        return plugins

    def collect_schema_extensions(self) -> list[StorageSchemaExtensionInterface]:
        """All ``StorageSchemaExtensionInterface`` plugins."""
        from mcs.interfaces.storage_schema_ext import (
            StorageSchemaExtensionInterface,
        )

        return self.get_all(StorageSchemaExtensionInterface)  # type: ignore[return-value]

    def collect_node_extensions(self) -> list[NodeExtensionInterface]:
        """All ``NodeExtensionInterface`` plugins (used by ContextRenderer)."""
        from mcs.interfaces.node_extension import NodeExtensionInterface

        return self.get_all(NodeExtensionInterface)  # type: ignore[return-value]

    def initialize_all(self, context: PluginContext) -> None:
        """Call ``initialize()`` on every registered plugin."""
        for plugin in self.plugins.values():
            plugin.initialize(context)

    def shutdown_all(self) -> None:
        """Call ``shutdown()`` on every registered plugin."""
        for plugin in self.plugins.values():
            plugin.shutdown()

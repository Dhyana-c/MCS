"""Plugin manager - register, lookup, and lifecycle-manage plugins.

See architecture.md §4.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcs.core.config import MCSConfig
    from mcs.core.graph import GraphStore
    from mcs.core.serializer import Serializer
    from mcs.core.token_budget import TokenBudget
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
    serializer: Serializer
    plugin_manager: PluginManager


class PluginManager:
    """Register, lookup, and lifecycle-manage plugins.

    Maintains two indexes:

    - ``plugins``: name -> Plugin
    - ``interfaces``: InterfaceClass -> [Plugin]

    See architecture.md §4.2.
    """

    def __init__(self) -> None:
        self.plugins: dict[str, Plugin] = {}
        self.interfaces: dict[type, list[Plugin]] = {}

    def register(self, plugin: Plugin) -> None:
        """Register a plugin and index it by all interfaces it implements."""
        self.plugins[plugin.name] = plugin
        for iface in plugin.interfaces:
            self.interfaces.setdefault(iface, []).append(plugin)

    def get(self, interface: type) -> Plugin | None:
        """Return the first plugin implementing the given interface, or None."""
        plugins = self.interfaces.get(interface, [])
        return plugins[0] if plugins else None

    def get_all(self, interface: type) -> list[Plugin]:
        """Return all plugins implementing the given interface."""
        return list(self.interfaces.get(interface, []))

    def collect_schema_extensions(self) -> list[StorageSchemaExtensionInterface]:
        """Return all plugins implementing StorageSchemaExtensionInterface.

        Used by storage plugins during ``initialize()`` to dynamically build
        their schema. See architecture.md §3.7.
        """
        from mcs.interfaces.storage_schema_ext import (
            StorageSchemaExtensionInterface,
        )

        return self.get_all(StorageSchemaExtensionInterface)  # type: ignore[return-value]

    def initialize_all(self, context: PluginContext) -> None:
        """Call ``initialize()`` on every registered plugin."""
        for plugin in self.plugins.values():
            plugin.initialize(context)

    def shutdown_all(self) -> None:
        """Call ``shutdown()`` on every registered plugin."""
        for plugin in self.plugins.values():
            plugin.shutdown()

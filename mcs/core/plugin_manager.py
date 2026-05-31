"""插件管理器 - 注册、查找和生命周期管理插件。

支持 openspec/specs/plugin-protocol/spec.md 中定义的 5 个新插件接口：

  - EntryPluginInterface       （按优先级排序的 get_all）
  - TrimPluginInterface
  - ArbitrationPluginInterface （单例强制）
  - PostprocessPluginInterface
  - CompactionPluginInterface

以及现有接口（Storage / Index / LLM / NodeExtension /
StorageSchemaExtension / Maintenance）。
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
    """注入到 ``Plugin.initialize()`` 中的运行时上下文。

    插件使用此上下文访问核心引擎对象并发现其他插件。
    """

    graph: GraphStore
    config: MCSConfig
    token_budget: TokenBudget
    context_renderer: ContextRenderer
    plugin_manager: PluginManager


class PluginManager:
    """注册、查找和生命周期管理插件。"""

    def __init__(self) -> None:
        self.plugins: dict[str, Plugin] = {}
        self.interfaces: dict[type, list[Plugin]] = {}

    def register(self, plugin: Plugin) -> None:
        """注册插件并按其实现的所有接口进行索引。

        如果注册此插件会违反单例约束（例如第二个 ArbitrationPlugin），
        则抛出 ``ConfigurationError``。
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
        """返回实现该接口的第一个插件，如果没有则返回 None。"""
        plugins = self.get_all(interface)
        return plugins[0] if plugins else None

    def get_all(self, interface: type) -> list[Plugin]:
        """返回实现该接口的所有插件。

        对于 ``EntryPluginInterface``，返回的列表按 ``priority`` 降序排序（最高优先）。
        同优先级保持注册顺序（Python 的 sorted 是稳定的）。
        """
        from mcs.interfaces.entry_plugin import EntryPluginInterface

        plugins = list(self.interfaces.get(interface, []))
        if interface is EntryPluginInterface:
            plugins.sort(key=lambda p: -p.priority)
        return plugins

    def collect_schema_extensions(self) -> list[StorageSchemaExtensionInterface]:
        """所有 ``StorageSchemaExtensionInterface`` 插件。"""
        from mcs.interfaces.storage_schema_ext import (
            StorageSchemaExtensionInterface,
        )

        return self.get_all(StorageSchemaExtensionInterface)  # type: ignore[return-value]

    def collect_node_extensions(self) -> list[NodeExtensionInterface]:
        """所有 ``NodeExtensionInterface`` 插件（由 ContextRenderer 使用）。"""
        from mcs.interfaces.node_extension import NodeExtensionInterface

        return self.get_all(NodeExtensionInterface)  # type: ignore[return-value]

    def initialize_all(self, context: PluginContext) -> None:
        """对所有已注册插件调用 ``initialize()``。"""
        for plugin in self.plugins.values():
            plugin.initialize(context)

    def shutdown_all(self) -> None:
        """对所有已注册插件调用 ``shutdown()``。"""
        for plugin in self.plugins.values():
            plugin.shutdown()

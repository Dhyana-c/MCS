"""插件管理器 - 注册、查找和生命周期管理插件。

按 PluginType 类型索引插件，不再依赖 interfaces 层。
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING

from mcs.core.errors import ConfigurationError
from mcs.core.plugin import Plugin, PluginType

if TYPE_CHECKING:
    from mcs.core.config import MCSConfig
    from mcs.core.context_renderer import ContextRenderer
    from mcs.core.graph import GraphStoreInterface
    from mcs.core.token_budget import TokenBudget


@dataclass
class PluginContext:
    """注入到 Plugin.initialize() 中的运行时上下文。

    插件使用此上下文访问核心引擎对象并发现其他插件。
    """

    graph: GraphStoreInterface
    config: MCSConfig
    token_budget: TokenBudget
    context_renderer: ContextRenderer
    plugin_manager: PluginManager


class PluginManager:
    """插件管理器 — 按 PluginType 类型索引和查找。"""

    def __init__(self) -> None:
        self._plugins: dict[str, Plugin] = {}
        self._by_type: dict[PluginType, list[Plugin]] = {}

    def register(self, plugin: Plugin) -> None:
        """注册插件。

        按 ``plugin.get_types()`` 把插件登记到其实现的每个类型下，
        使多接口插件（如同时是 NodeExtension 与 StorageSchemaExtension
        的 SourceTracking）可被任意一个类型查找到。

        Raises:
            ValueError: 如果同名插件已注册。
            ConfigurationError: 如果尝试注册第二个 ArbitrationPlugin。
        """
        name = plugin.get_name()
        if name in self._plugins:
            raise ValueError(f"Plugin {name!r} already registered")

        types = plugin.get_types()

        # ArbitrationPlugin 单例强制执行
        if PluginType.ARBITRATION in types and self._by_type.get(PluginType.ARBITRATION):
            raise ConfigurationError(
                f"只能注册一个 ArbitrationPlugin，已存在: "
                f"{self._by_type[PluginType.ARBITRATION][0].get_name()}"
            )

        self._plugins[name] = plugin
        for plugin_type in types:
            self._by_type.setdefault(plugin_type, []).append(plugin)

    def get(self, plugin_type: PluginType) -> Plugin | None:
        """返回指定类型的第一个插件（按 priority 降序）。"""
        plugins = self.get_all(plugin_type)
        return plugins[0] if plugins else None

    def get_all(self, plugin_type: PluginType) -> list[Plugin]:
        """返回指定类型的所有插件，按 priority 降序排列。"""
        plugins = list(self._by_type.get(plugin_type, []))
        plugins.sort(key=lambda p: -p.get_priority())
        return plugins

    def get_by_name(self, name: str) -> Plugin | None:
        """按名称查找插件。"""
        return self._plugins.get(name)

    def initialize_all(self, context: PluginContext) -> None:
        """初始化所有插件。"""
        for plugin in self._plugins.values():
            plugin.initialize(context)

    def shutdown_all(self) -> None:
        """关闭所有插件。"""
        for plugin in self._plugins.values():
            plugin.shutdown()

"""插件基类。

参见 architecture.md §4.1。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, ClassVar

if TYPE_CHECKING:
    from mcs.core.plugin_manager import PluginContext


class Plugin(ABC):
    """所有 MCS 插件的基类。

    子类需设置以下类属性：

    - ``name`` (str): 插件标识符；对于 NodeExtension 插件，也是
      ``node.extensions[name]`` 的键名。
    - ``version`` (str): 语义版本字符串。
    - ``interfaces`` (list[type]): 此插件实现的接口列表
      (由 ``PluginManager.register`` 用于索引插件)。

    参见 architecture.md §4.1。
    """

    name: ClassVar[str] = ""
    version: ClassVar[str] = "0.1.0"
    interfaces: ClassVar[list[type]] = []

    def __init__(self, config: dict | None = None) -> None:
        self.config = config or {}

    @abstractmethod
    def initialize(self, context: PluginContext) -> None:
        """初始化插件 (由 PluginManager 在注册后调用)。"""
        pass

    @abstractmethod
    def shutdown(self) -> None:
        """清理插件资源。"""
        pass

"""MCSBuilder 抽象基类 — 只依赖 MCSConfig 的构建契约。

将 MCS 实例构建过程抽象化，让子类决定如何查找插件类。
这样 core 层不依赖具体 plugins 实现，实现关注点分离。

参见 openspec/specs/mcs-builder/spec.md "MCSBuilder 抽象基类定义构建契约"。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcs.core.mcs import MCS
    from mcs.core.plugin import Plugin


class MCSBuilder(ABC):
    """抽象构建器 — 只依赖 MCSConfig。

    子类需实现 ``get_plugin_class()`` 方法，根据插件名称返回插件类。
    ``build()`` 方法封装从配置到初始化完成的整个构建流程。
    """

    def __init__(self, config: "MCSConfig"):
        """初始化构建器。

        Args:
            config: MCS 配置对象
        """
        self.config = config

    @abstractmethod
    def get_plugin_class(self, name: str) -> type["Plugin"] | None:
        """根据插件名称返回插件类。

        Args:
            name: 插件名称（如 "sqlite_storage", "deepseek_llm"）

        Returns:
            插件类，若未找到则返回 None
        """
        ...

    def build(self) -> "MCS":
        """构建并初始化 MCS 实例。

        Returns:
            已完成 ``initialize()`` 的 MCS 实例
        """
        from mcs.core.mcs import MCS

        registry = self._collect_registry()
        mcs = MCS(self.config, plugin_registry=registry)
        mcs.initialize()
        return mcs

    def _collect_registry(self) -> dict[str, type["Plugin"]]:
        """从 shared + write + read + LLM 收集插件注册表。

        Returns:
            插件名称 → 插件类的映射
        """
        all_names: list[str] = []

        # 收集所有插件名称（去重）
        seen: set[str] = set()
        for name in (
            self.config.shared_plugins +
            self.config.write_plugins +
            self.config.read_plugins
        ):
            if name not in seen:
                all_names.append(name)
                seen.add(name)

        # LLM 也加入（即使不在 plugins 列表中）
        for llm in [self.config.write_llm, self.config.read_llm]:
            if llm and llm not in seen:
                all_names.append(llm)
                seen.add(llm)

        # 查找插件类
        registry: dict[str, type["Plugin"]] = {}
        for name in all_names:
            cls = self.get_plugin_class(name)
            if cls is not None:
                registry[name] = cls

        return registry

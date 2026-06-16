"""节点扩展接口 - 插件通过 extensions 字典扩展 Node。

参见 openspec/specs/plugin-protocol/spec.md "NodeExtensionInterface"。
"""

from __future__ import annotations

from abc import abstractmethod
from typing import TYPE_CHECKING, Any

from mcs.core.plugin import Plugin, PluginType

if TYPE_CHECKING:
    from mcs.entities.graph import Node


class NodeExtensionInterface(Plugin):
    """抽象节点数据扩展。

    插件通过其 get_name() 返回的名称作为 node.extensions 的键。
    """

    def get_type(self) -> PluginType:
        return PluginType.NODE_EXTENSION

    def execute(self, **kwargs):
        """节点扩展插件无统一执行语义。"""
        raise NotImplementedError("NodeExtensionInterface does not support execute()")

    @abstractmethod
    def schema(self) -> dict:
        """字段类型定义：{field_name: type_str}。"""
        pass

    @abstractmethod
    def default(self) -> Any:
        """新节点上扩展槽位的默认值。"""
        pass

    @abstractmethod
    def serialize(self, data: Any) -> dict:
        """将扩展数据转换为可 JSON 序列化的字典。"""
        pass

    @abstractmethod
    def deserialize(self, data: dict) -> Any:
        """从序列化形式恢复扩展数据。"""
        pass

    # === 可选：提示词渲染贡献 ===

    def render(self, node: Node, purpose: str) -> str | None:
        """在为 purpose 渲染 node 时贡献提示词片段。

        默认返回 None（不贡献）。
        """
        return None

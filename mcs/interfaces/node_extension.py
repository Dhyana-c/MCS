"""节点扩展接口 - 插件通过 extensions 字典扩展 Node。

插件类使用其 ``name`` 类属性（继承自 ``Plugin``）
作为 ``node.extensions[name]`` 的键。实现类声明其管理的字段
以及如何序列化这些字段。

除 schema/default/serialize/deserialize 外，扩展还可以
重写 ``render(node, purpose)``，在 ``ContextRenderer`` 为特定 LLM 用途
序列化节点时贡献提示词片段。

参见 openspec/specs/plugin-protocol/spec.md "NodeExtensionInterface supports
按 purpose 贡献渲染片段"。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mcs.core.graph import Node


class NodeExtensionInterface(ABC):
    """抽象节点数据扩展。

    注意：``name`` 由 ``Plugin`` 基类作为类属性提供，是
    ``node.extensions`` 的键。此处有意不定义为抽象方法，
    以避免多重继承冲突。
    """

    @abstractmethod
    def schema(self) -> dict:
        """字段类型定义：``{field_name: type_str}``。"""
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
        """在为 ``purpose`` 渲染 ``node`` 时贡献提示词片段。

        默认返回 None（不贡献）。希望在核心 ``name`` / ``content`` / ``summary``
        字段之外添加信息的扩展（例如来源、版本、置信度）可以重写此方法
        并返回简短的字符串片段。

        当此扩展对给定用途没有内容可贡献时返回 ``None``。
        ``ContextRenderer`` 会跳过 None 贡献。
        """
        return None

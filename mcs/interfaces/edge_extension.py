"""边扩展接口 - 插件通过 extensions 字典扩展 Edge。

与 ``NodeExtensionInterface`` 镜像：插件经其 ``get_name()`` 作为 ``edge.extensions`` 的键，
按 ``purpose`` 决定是否为某次 LLM 渲染贡献片段（``render(edge, purpose)`` 返回 ``None``
即隐藏、不渲染，与节点扩展共用同一可见性判定规则）。

参见 openspec/specs/plugin-protocol/spec.md "EdgeExtensionInterface"
与 edge-extension-model capability spec。
"""

from __future__ import annotations

from abc import abstractmethod
from typing import TYPE_CHECKING, Any

from mcs.core.plugin import Plugin, PluginType

if TYPE_CHECKING:
    from mcs.entities.graph import Edge


class EdgeExtensionInterface(Plugin):
    """抽象边数据扩展。

    插件通过其 get_name() 返回的名称作为 edge.extensions 的键。
    """

    def get_type(self) -> PluginType:
        return PluginType.EDGE_EXTENSION

    def execute(self, **kwargs):
        """边扩展插件无统一执行语义。"""
        raise NotImplementedError("EdgeExtensionInterface does not support execute()")

    @abstractmethod
    def schema(self) -> dict:
        """字段类型定义：{field_name: type_str}。"""
        pass

    @abstractmethod
    def default(self) -> Any:
        """新边上扩展槽位的默认值。"""
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

    def render(self, edge: Edge, purpose: str) -> str | None:
        """在为 purpose 渲染 edge 时贡献提示词片段。

        默认返回 None（不贡献）。返回片段=该字段在此 purpose 下可见；
        返回 None=隐藏、不进渲染文本（与 NodeExtensionInterface 共用同一规则）。
        """
        return None

"""SummaryPlugin - 管理 ``extensions['summary']`` 槽位。

生成由 ``SummaryRegenPlugin`` (压缩) 在写入阶段 ⑥ 触发。
此插件仅拥有数据槽模式的定义。
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any

from mcs.core.plugin import PluginType
from mcs.interfaces.node_extension import NodeExtensionInterface

if TYPE_CHECKING:
    from mcs.core.plugin_manager import PluginContext
    from mcs.entities.graph import Node


class SummaryPlugin(NodeExtensionInterface):
    """``extensions["summary"]`` = ``{"text": str, "generated_at": str|None}``."""

    def __init__(self, config: dict | None = None) -> None:
        super().__init__(config)

    # === Plugin 基类方法 ===

    def get_name(self) -> str:
        return "summary"

    # === 插件生命周期 ===

    def initialize(self, context: PluginContext) -> None:
        return None

    def shutdown(self) -> None:
        return None

    # === NodeExtensionInterface ===

    def schema(self) -> dict:
        return {"text": "str", "generated_at": "iso8601 str | None"}

    def default(self) -> dict:
        return {"text": "", "generated_at": None}

    def serialize(self, data: Any) -> dict:
        if not data:
            return self.default()
        generated_at = data.get("generated_at")
        if isinstance(generated_at, datetime):
            generated_at = generated_at.isoformat()
        return {
            "text": data.get("text", ""),
            "generated_at": generated_at,
        }

    def deserialize(self, data: dict) -> dict:
        if not data:
            return self.default()
        return {
            "text": data.get("text", ""),
            "generated_at": data.get("generated_at"),
        }

    def render(self, node: Node, purpose: str) -> str | None:
        """SummaryPlugin 不提供渲染——ContextRenderer 在降级
        内容为摘要时直接读取 ``extensions["summary"]["text"]``。
        """
        return None

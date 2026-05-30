"""SummaryPlugin - manage ``extensions['summary']`` slot.

Generation is triggered by ``SummaryRegenPlugin`` (Compaction) in write
stage ⑥. This plugin only owns the data slot schema.
"""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING, Any, ClassVar

from mcs.interfaces.node_extension import NodeExtensionInterface
from mcs.plugins.base import Plugin

if TYPE_CHECKING:
    from mcs.core.graph import Node
    from mcs.core.plugin_manager import PluginContext


class SummaryPlugin(Plugin, NodeExtensionInterface):
    """``extensions["summary"]`` = ``{"text": str, "generated_at": str|None}``."""

    name: ClassVar[str] = "summary"
    version: ClassVar[str] = "0.1.0"
    interfaces: ClassVar[list[type]] = [NodeExtensionInterface]

    def __init__(self, config: dict | None = None) -> None:
        super().__init__(config)

    # === Plugin lifecycle ===

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
        """SummaryPlugin contributes nothing — ContextRenderer reads
        ``extensions["summary"]["text"]`` directly when downgrading
        content to summary.
        """
        return None

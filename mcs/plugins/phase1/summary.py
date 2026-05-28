"""SummaryPlugin - LLM-generated node summaries.

Implements two interfaces:

- ``NodeExtensionInterface``: manages ``node.extensions["summary"]``
- ``PipelineHookInterface``: generates summary on_created_or_merged

See architecture.md §6.2.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

from mcs.interfaces.node_extension import NodeExtensionInterface
from mcs.interfaces.pipeline_hook import PipelineHookInterface
from mcs.plugins.base import Plugin

if TYPE_CHECKING:
    from mcs.core.plugin_manager import PluginContext


class SummaryPlugin(Plugin, NodeExtensionInterface, PipelineHookInterface):
    """LLM-generated node summary plugin.

    Phase 1 implementation pending. See architecture.md §6.2.
    """

    name: ClassVar[str] = "summary"
    version: ClassVar[str] = "0.1.0"
    interfaces: ClassVar[list[type]] = [
        NodeExtensionInterface,
        PipelineHookInterface,
    ]

    def __init__(self, config: dict | None = None) -> None:
        super().__init__(config)
        self.llm: Any = None

    # === Plugin lifecycle ===

    def initialize(self, context: PluginContext) -> None:
        raise NotImplementedError("Phase 1 implementation pending")

    def shutdown(self) -> None:
        raise NotImplementedError("Phase 1 implementation pending")

    # === NodeExtensionInterface ===

    def schema(self) -> dict:
        raise NotImplementedError("Phase 1 implementation pending")

    def default(self) -> Any:
        raise NotImplementedError("Phase 1 implementation pending")

    def serialize(self, data: Any) -> dict:
        raise NotImplementedError("Phase 1 implementation pending")

    def deserialize(self, data: dict) -> Any:
        raise NotImplementedError("Phase 1 implementation pending")

    # === PipelineHookInterface ===
    # Phase 1 override on_created_or_merged: call self.llm.generate_summary()
    # and mount to node.extensions["summary"] = {"text": ..., "generated_at": ...}

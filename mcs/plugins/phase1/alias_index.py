"""AliasIndexPlugin - alias dictionary + node extension + pipeline hook.

Implements three interfaces:

- ``IndexInterface``: lookup for seed location and write-side anchor finding
- ``NodeExtensionInterface``: manages ``node.extensions["alias_index"]``
- ``PipelineHookInterface``: generates aliases on_extracted, updates index
  on_created_or_merged

See architecture.md §6.1.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

from mcs.interfaces.index import IndexInterface
from mcs.interfaces.node_extension import NodeExtensionInterface
from mcs.interfaces.pipeline_hook import PipelineHookInterface
from mcs.plugins.base import Plugin

if TYPE_CHECKING:
    from mcs.core.graph import GraphStore, Node
    from mcs.core.plugin_manager import PluginContext


class AliasIndexPlugin(
    Plugin, IndexInterface, NodeExtensionInterface, PipelineHookInterface
):
    """Alias dictionary index + node extension + pipeline hook.

    Phase 1 implementation pending. See architecture.md §6.1.
    """

    name: ClassVar[str] = "alias_index"
    version: ClassVar[str] = "0.1.0"
    interfaces: ClassVar[list[type]] = [
        IndexInterface,
        NodeExtensionInterface,
        PipelineHookInterface,
    ]

    def __init__(self, config: dict | None = None) -> None:
        super().__init__(config)
        self.index: dict[str, list[str]] = {}
        self.tokenizer: Any = None
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

    # === IndexInterface ===

    def build(self, graph: GraphStore) -> None:
        raise NotImplementedError("Phase 1 implementation pending")

    def lookup(self, query: str) -> list[str]:
        raise NotImplementedError("Phase 1 implementation pending")

    def add_entry(self, node: Node) -> None:
        raise NotImplementedError("Phase 1 implementation pending")

    def remove_entry(self, node_id: str) -> None:
        raise NotImplementedError("Phase 1 implementation pending")

    def update_entry(self, node: Node) -> None:
        raise NotImplementedError("Phase 1 implementation pending")

    # === PipelineHookInterface ===
    # on_<state> methods inherited as empty defaults. Phase 1 will override:
    #   - on_extracted: call self.llm.generate_aliases() for each concept
    #   - on_created_or_merged: mount aliases to node.extensions[name],
    #     then update self.index

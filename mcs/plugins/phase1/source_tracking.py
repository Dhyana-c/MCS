"""SourceTrackingPlugin - document-chunk source tracking + idempotency.

Implements three interfaces:

- ``NodeExtensionInterface``: manages ``node.extensions["source_tracking"]``
  which holds a list of ``Source`` records
- ``PipelineHookInterface``: idempotency check on_ingest_start (sets
  ``ctx.skip``), appends source on_created_or_merged, logs chunk on_ingest_end
- ``StorageSchemaExtensionInterface``: registers the ``document_chunks`` table
  for idempotency checks

Also exposes the ``Source`` dataclass and two public API methods
(``update_document`` and ``purge_orphans``) used by application code for
document revision.

See architecture.md §6.3.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, ClassVar

from mcs.interfaces.node_extension import NodeExtensionInterface
from mcs.interfaces.pipeline_hook import PipelineHookInterface
from mcs.interfaces.storage_schema_ext import StorageSchemaExtensionInterface
from mcs.plugins.base import Plugin

if TYPE_CHECKING:
    from mcs.core.graph import GraphStore
    from mcs.core.plugin_manager import PluginContext
    from mcs.core.write_pipeline import WritePipeline


@dataclass
class Source:
    """Concept source (document-chunk level).

    Phase 2 may extend this to reference ``fact_id`` when EventLayer is added;
    the schema is forward-compatible.
    """

    doc_id: str
    chunk_id: str
    content_hash: str
    section_title: str | None = None


class SourceTrackingPlugin(
    Plugin,
    NodeExtensionInterface,
    PipelineHookInterface,
    StorageSchemaExtensionInterface,
):
    """Source tracking, idempotent re-ingestion, and document revision.

    Phase 1 implementation pending. See architecture.md §6.3.
    """

    name: ClassVar[str] = "source_tracking"
    version: ClassVar[str] = "0.1.0"
    interfaces: ClassVar[list[type]] = [
        NodeExtensionInterface,
        PipelineHookInterface,
        StorageSchemaExtensionInterface,
    ]

    def __init__(self, config: dict | None = None) -> None:
        super().__init__(config)
        self.storage: Any = None

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

    # === StorageSchemaExtensionInterface ===

    def node_columns(self) -> dict[str, str]:
        raise NotImplementedError("Phase 1 implementation pending")

    def auxiliary_tables(self) -> dict[str, str]:
        raise NotImplementedError("Phase 1 implementation pending")

    # === PipelineHookInterface ===
    # Phase 1 will override:
    #   - on_ingest_start: idempotency check, set ctx.skip if duplicate
    #   - on_created_or_merged: append Source to node.extensions[name]["sources"]
    #   - on_ingest_end: log chunk in document_chunks table

    # === Public API ===

    def update_document(
        self,
        doc_id: str,
        new_chunks: list,
        pipeline: WritePipeline,
    ) -> None:
        """Replace all chunks of a document with new content.

        Phase 1 implementation pending. See architecture.md §6.3.
        """
        raise NotImplementedError("Phase 1 implementation pending")

    def purge_orphans(self, graph: GraphStore) -> list[str]:
        """Remove nodes whose sources slot is empty. Returns removed node IDs.

        Must be called explicitly after batch document updates; never auto-runs.
        """
        raise NotImplementedError("Phase 1 implementation pending")

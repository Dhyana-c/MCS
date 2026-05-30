"""SourceTrackingPlugin and IdempotencyCheckPlugin.

- ``SourceTrackingPlugin``: manages ``extensions["source_tracking"]``;
  contributes 出处 fragment when ``purpose == "synthesize"``; registers
  the ``document_chunks`` storage table.
- ``IdempotencyCheckPlugin``: mounted at write-stage ① preprocess to
  short-circuit re-ingestion of the same ``(doc_id, chunk_id,
  content_hash)`` tuple.
"""

from __future__ import annotations

import hashlib
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Any, ClassVar

from mcs.interfaces.node_extension import NodeExtensionInterface
from mcs.interfaces.postprocess_plugin import PostprocessPluginInterface
from mcs.interfaces.storage_schema_ext import StorageSchemaExtensionInterface
from mcs.plugins.base import Plugin

if TYPE_CHECKING:
    from mcs.core.graph import GraphStore, Node
    from mcs.core.plugin_manager import PluginContext
    from mcs.core.write_pipeline import WritePipeline


@dataclass
class Source:
    """Concept source (document-chunk level).

    Phase 2 may extend this to reference ``fact_id`` when EventLayer is
    added; the schema is forward-compatible.
    """

    doc_id: str
    chunk_id: str
    content_hash: str
    section_title: str | None = None


class SourceTrackingPlugin(
    Plugin,
    NodeExtensionInterface,
    StorageSchemaExtensionInterface,
):
    """``extensions["source_tracking"]`` = ``{"sources": [Source, ...]}``.

    Renders an 出处 fragment ONLY when ``purpose == "synthesize"`` so
    consumers can attribute answers back to source chunks.
    """

    name: ClassVar[str] = "source_tracking"
    version: ClassVar[str] = "0.1.0"
    interfaces: ClassVar[list[type]] = [
        NodeExtensionInterface,
        StorageSchemaExtensionInterface,
    ]

    def __init__(self, config: dict | None = None) -> None:
        super().__init__(config)
        self.storage: Any = None
        self.graph: GraphStore | None = None

    # === Plugin lifecycle ===

    def initialize(self, context: PluginContext) -> None:
        from mcs.interfaces.storage import StorageInterface

        self.graph = context.graph
        self.storage = context.plugin_manager.get(StorageInterface)

    def shutdown(self) -> None:
        self.storage = None

    # === NodeExtensionInterface ===

    def schema(self) -> dict:
        return {"sources": "list[Source]"}

    def default(self) -> dict:
        return {"sources": []}

    def serialize(self, data: Any) -> dict:
        if not data:
            return self.default()
        return {
            "sources": [
                asdict(s) if isinstance(s, Source) else dict(s)
                for s in data.get("sources", [])
            ]
        }

    def deserialize(self, data: dict) -> dict:
        if not data:
            return self.default()
        return {
            "sources": [Source(**s) for s in data.get("sources", [])]
        }

    def render(self, node: Node, purpose: str) -> str | None:
        if purpose != "synthesize":
            return None
        sources = (node.extensions or {}).get(self.name, {}).get("sources", [])
        if not sources:
            return None
        refs = []
        for s in sources[:3]:  # show up to 3 sources
            doc_id = s.doc_id if isinstance(s, Source) else s.get("doc_id", "?")
            chunk_id = (
                s.chunk_id if isinstance(s, Source) else s.get("chunk_id", "?")
            )
            refs.append(f"{doc_id}/{chunk_id}")
        suffix = "…" if len(sources) > 3 else ""
        return f"出处: {', '.join(refs)}{suffix}"

    # === StorageSchemaExtensionInterface ===

    def node_columns(self) -> dict[str, str]:
        return {}  # sources travel in the extensions_json blob

    def auxiliary_tables(self) -> dict[str, str]:
        return {
            "document_chunks": """
                CREATE TABLE IF NOT EXISTS document_chunks (
                    doc_id TEXT NOT NULL,
                    chunk_id TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    ingested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (doc_id, chunk_id)
                )
            """
        }

    # === Public API ===

    def update_document(
        self,
        doc_id: str,
        new_chunks: list,
        pipeline: WritePipeline,
    ) -> None:
        """Replace all chunks of a document with new content.

        ``new_chunks`` items can be dicts ``{id, text, section_title?}`` or
        objects with the same attributes.
        """
        new_keys: set[tuple[str, str]] = set()
        for chunk in new_chunks:
            chunk_id = _get(chunk, "id")
            text = _get(chunk, "text")
            section_title = _get(chunk, "section_title", None)
            pipeline.ingest(
                text,
                doc_id=doc_id,
                chunk_id=chunk_id,
                section_title=section_title,
            )
            new_keys.add((doc_id, chunk_id))

        # Drop sources for chunks that no longer exist in the new revision.
        if self.graph is None:
            return
        for node in self.graph.get_all_nodes():
            slot = (node.extensions or {}).get(self.name, {})
            sources = slot.get("sources", [])
            if not sources:
                continue
            kept = []
            for s in sources:
                s_doc = s.doc_id if isinstance(s, Source) else s.get("doc_id")
                s_chunk = s.chunk_id if isinstance(s, Source) else s.get("chunk_id")
                # Keep sources from other documents OR chunks still in the new revision.
                if s_doc != doc_id or (s_doc, s_chunk) in new_keys:
                    kept.append(s)
            slot["sources"] = kept

    def purge_orphans(self, graph: GraphStore) -> list[str]:
        """Remove nodes whose sources slot is empty (no surviving evidence).

        Must be called explicitly after batch document updates.
        """
        orphans: list[str] = []
        for node in graph.get_all_nodes():
            slot = (node.extensions or {}).get(self.name, {})
            if not slot.get("sources"):
                orphans.append(node.id)
        for nid in orphans:
            graph.delete_node(nid)
        return orphans


class IdempotencyCheckPlugin(Plugin, PostprocessPluginInterface):
    """Write-stage ① idempotency check.

    Computes a content hash and consults the storage's ``document_chunks``
    table; if the chunk was already ingested, sets ``ctx.skip = True`` so
    the rest of the write pipeline short-circuits. Otherwise records the
    chunk and stages a ``Source`` on the context for later attachment.
    """

    name: ClassVar[str] = "idempotency_check"
    version: ClassVar[str] = "0.1.0"
    interfaces: ClassVar[list[type]] = [PostprocessPluginInterface]
    position: ClassVar[str] = "write_preprocess"

    def __init__(self, config: dict | None = None) -> None:
        super().__init__(config)
        self.storage: Any = None
        self.source_tracking: SourceTrackingPlugin | None = None

    def initialize(self, context: PluginContext) -> None:
        from mcs.interfaces.storage import StorageInterface

        self.storage = context.plugin_manager.get(StorageInterface)
        # Locate the SourceTracking plugin by interface
        for p in context.plugin_manager.get_all(NodeExtensionInterface):
            if isinstance(p, SourceTrackingPlugin):
                self.source_tracking = p
                break

    def shutdown(self) -> None:
        self.storage = None

    def process(self, input: Any, ctx: Any) -> Any:
        text = input if isinstance(input, str) else ""
        metadata = getattr(ctx, "metadata", {}) or {}
        doc_id = metadata.get("doc_id")
        chunk_id = metadata.get("chunk_id")
        if not (doc_id and chunk_id):
            return text  # no doc context → nothing to deduplicate

        content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
        if self._already_ingested(doc_id, chunk_id, content_hash):
            ctx.skip = True
            return text

        # Stage Source for downstream attachment (in ctx.metadata).
        section_title = metadata.get("section_title")
        metadata["_pending_source"] = Source(
            doc_id=doc_id,
            chunk_id=chunk_id,
            content_hash=content_hash,
            section_title=section_title,
        )
        self._record_chunk(doc_id, chunk_id, content_hash)
        return text

    # === Internal storage helpers ===

    def _already_ingested(
        self, doc_id: str, chunk_id: str, content_hash: str
    ) -> bool:
        conn = getattr(self.storage, "conn", None)
        if conn is None:
            return False
        row = conn.execute(
            "SELECT content_hash FROM document_chunks "
            "WHERE doc_id=? AND chunk_id=?",
            (doc_id, chunk_id),
        ).fetchone()
        return bool(row and row[0] == content_hash)

    def _record_chunk(
        self, doc_id: str, chunk_id: str, content_hash: str
    ) -> None:
        conn = getattr(self.storage, "conn", None)
        if conn is None:
            return
        conn.execute(
            "INSERT OR REPLACE INTO document_chunks "
            "(doc_id, chunk_id, content_hash) VALUES (?, ?, ?)",
            (doc_id, chunk_id, content_hash),
        )
        conn.commit()


def _get(obj: Any, attr: str, default: Any = None) -> Any:
    """Read ``attr`` from a dict or attribute access."""
    if isinstance(obj, dict):
        return obj.get(attr, default)
    return getattr(obj, attr, default)

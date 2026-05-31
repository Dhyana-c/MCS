"""SourceTrackingPlugin 和 IdempotencyCheckPlugin。

- ``SourceTrackingPlugin``: 管理 ``extensions["source_tracking"]``；
  当 ``purpose == "synthesize"`` 时提供出处片段；注册
  ``document_chunks`` 存储表。
- ``IdempotencyCheckPlugin``: 挂载于写入阶段 ① 预处理，用于
  短路重复摄入相同的 ``(doc_id, chunk_id, content_hash)`` 元组。
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
    """概念来源（文档-块级别）。

    Phase 2 可能会扩展此结构以引用 ``fact_id``（当 EventLayer
    添加时）；该模式具有向前兼容性。
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
    """``extensions["source_tracking"]`` = ``{"sources": [Source, ...]}``。

    仅当 ``purpose == "synthesize"`` 时渲染出处片段，以便
    消费者可以将答案归因于来源块。
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

    # === 插件生命周期 ===

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
        for s in sources[:3]:  # 最多显示 3 个来源
            doc_id = s.doc_id if isinstance(s, Source) else s.get("doc_id", "?")
            chunk_id = (
                s.chunk_id if isinstance(s, Source) else s.get("chunk_id", "?")
            )
            refs.append(f"{doc_id}/{chunk_id}")
        suffix = "…" if len(sources) > 3 else ""
        return f"出处: {', '.join(refs)}{suffix}"

    # === StorageSchemaExtensionInterface ===

    def node_columns(self) -> dict[str, str]:
        return {}  # sources 存储在 extensions_json 字段中

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

    # === 公共 API ===

    def update_document(
        self,
        doc_id: str,
        new_chunks: list,
        pipeline: WritePipeline,
    ) -> None:
        """用新内容替换文档的所有块。

        ``new_chunks`` 中的元素可以是字典 ``{id, text, section_title?}``
        或具有相同属性的对象。
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

        # 删除新版本中不再存在的块的来源。
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
                # 保留来自其他文档的来源，或新版本中仍存在的块。
                if s_doc != doc_id or (s_doc, s_chunk) in new_keys:
                    kept.append(s)
            slot["sources"] = kept

    def purge_orphans(self, graph: GraphStore) -> list[str]:
        """移除来源槽位为空的节点（无存活的证据）。

        必须在批量文档更新后显式调用。
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
    """写入阶段 ① 的幂等性检查。

    计算内容哈希并查询存储的 ``document_chunks`` 表；如果该块
    已被摄入，则设置 ``ctx.skip = True`` 以短路写入管道的
    其余部分。否则记录该块并在上下文中暂存一个 ``Source``
    以供后续附加。
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
        # 通过接口定位 SourceTracking 插件
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
            return text  # 无文档上下文 → 无需去重

        content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
        if self._already_ingested(doc_id, chunk_id, content_hash):
            ctx.skip = True
            return text

        # 为下游附加暂存 Source（在 ctx.metadata 中）。
        section_title = metadata.get("section_title")
        metadata["_pending_source"] = Source(
            doc_id=doc_id,
            chunk_id=chunk_id,
            content_hash=content_hash,
            section_title=section_title,
        )
        self._record_chunk(doc_id, chunk_id, content_hash)
        return text

    # === 内部存储辅助方法 ===

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
    """从字典或对象属性中读取 ``attr``。"""
    if isinstance(obj, dict):
        return obj.get(attr, default)
    return getattr(obj, attr, default)

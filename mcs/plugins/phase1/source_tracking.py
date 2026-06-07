"""SourceTrackingPlugin 和 IdempotencyCheckPlugin。

- ``SourceTrackingPlugin``: 管理 ``extensions["source_tracking"]``；
  当 ``purpose == "synthesize"`` 时提供出处片段；注册
  ``document_chunks`` 存储表。
- ``IdempotencyCheckPlugin``: 挂载于写入阶段 ① 预处理，用于
  短路重复摄入相同的 ``(doc_id, chunk_id, content_hash)`` 元组。
"""

from __future__ import annotations

import ast
import hashlib
import re
from dataclasses import asdict, dataclass
from typing import TYPE_CHECKING, Any

from mcs.core.plugin import PluginType
from mcs.interfaces.node_extension import NodeExtensionInterface
from mcs.interfaces.preprocess_plugin import PreprocessPluginInterface
from mcs.interfaces.storage_schema_ext import StorageSchemaExtensionInterface

if TYPE_CHECKING:
    from mcs.core.graph import Node
    from mcs.core.plugin_manager import PluginContext
    from mcs.core.store import StoreInterface
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


# 历史 db 里 source 曾被 ``json.dumps(default=str)`` 存成 ``Source(...)`` repr 字符串。
# 用正则定位每个 ``key=<python字面量>``，再 ast.literal_eval 还原（天然处理引号转义/None）。
_SOURCE_KV_RE = re.compile(
    r"(\w+)\s*=\s*(\'(?:[^\'\\]|\\.)*\'|\"(?:[^\"\\]|\\.)*\"|None|\d+)"
)


def _parse_source_repr(s: str) -> dict:
    """从字符串化的 ``Source(doc_id='…', …)`` 中抽取字段（向后兼容，D5）。"""
    fields: dict[str, Any] = {}
    for m in _SOURCE_KV_RE.finditer(s):
        key, raw = m.group(1), m.group(2)
        try:
            fields[key] = ast.literal_eval(raw)
        except Exception:
            fields[key] = None
    return fields


def _coerce_source(s: Any) -> Source | None:
    """把一条来源记录归一为 ``Source``。

    接受 ``Source`` / dict / 历史 repr 字符串三种形态；无法识别返回 None。
    """
    if isinstance(s, Source):
        return s
    if isinstance(s, str):
        f = _parse_source_repr(s)
    elif isinstance(s, dict):
        f = s
    else:
        return None
    return Source(
        doc_id=f.get("doc_id") or "",
        chunk_id=f.get("chunk_id") or "",
        content_hash=f.get("content_hash") or "",
        section_title=f.get("section_title"),
    )


class SourceTrackingPlugin(
    NodeExtensionInterface,
    StorageSchemaExtensionInterface,
):
    """``extensions["source_tracking"]`` = ``{"sources": [Source, ...]}``。

    仅当 ``purpose == "synthesize"`` 时渲染出处片段，以便
    消费者可以将答案归因于来源块。
    """

    def __init__(self, config: dict | None = None) -> None:
        super().__init__(config)
        self.storage: Any = None
        self.store: StoreInterface | None = None

    # === Plugin 基类方法 ===

    def get_name(self) -> str:
        return "source_tracking"

    def get_type(self) -> PluginType:
        # 多接口插件，返回主类型
        return PluginType.NODE_EXTENSION

    def get_types(self) -> set[PluginType]:
        # 同时实现 NodeExtension 与 StorageSchemaExtension，两类型都登记
        return {PluginType.NODE_EXTENSION, PluginType.STORAGE_SCHEMA_EXT}

    # === 插件生命周期 ===

    def initialize(self, context: PluginContext) -> None:
        from mcs.stores.sqlite_store import SQLiteStore

        self.store = context.store
        # 获取 SQLiteStore 的 conn 用于 idempotency 检查
        if isinstance(self.store, SQLiteStore):
            self.storage = self.store
        else:
            self.storage = None

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
        out: list[Source] = []
        for s in data.get("sources", []):
            coerced = _coerce_source(s)
            if coerced is not None:
                out.append(coerced)
        return {"sources": out}

    def render(self, node: Node, purpose: str) -> str | None:
        if purpose != "synthesize":
            return None
        sources = (node.extensions or {}).get(self.get_name(), {}).get("sources", [])
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
        if self.store is None:
            return
        for node in self.store.get_all_nodes():
            slot = (node.extensions or {}).get(self.get_name(), {})
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

    def purge_orphans(self, store: StoreInterface) -> list[str]:
        """移除来源槽位为空的节点（无存活的证据）。

        必须在批量文档更新后显式调用。
        """
        orphans: list[str] = []
        for node in store.get_all_nodes():
            slot = (node.extensions or {}).get(self.get_name(), {})
            if not slot.get("sources"):
                orphans.append(node.id)
        for nid in orphans:
            store.delete_node(nid)
        return orphans


class IdempotencyCheckPlugin(PreprocessPluginInterface):
    """写入阶段 ① 的幂等性检查。

    计算内容哈希并查询存储的 ``document_chunks`` 表；如果该块
    已被摄入，则设置 ``ctx.skip = True`` 以短路写入管道的
    其余部分。否则记录该块并在上下文中暂存一个 ``Source``
    以供后续附加。
    """

    def __init__(self, config: dict | None = None) -> None:
        super().__init__(config)
        self.storage: Any = None
        self.source_tracking: SourceTrackingPlugin | None = None

    # === Plugin 基类方法 ===

    def get_name(self) -> str:
        return "idempotency_check"

    # === 插件生命周期 ===

    def initialize(self, context: PluginContext) -> None:
        from mcs.core.plugin import PluginType
        from mcs.stores.sqlite_store import SQLiteStore

        if isinstance(context.store, SQLiteStore):
            self.storage = context.store
        else:
            self.storage = None
        # 通过接口定位 SourceTracking 插件
        for p in context.plugin_manager.get_all(PluginType.NODE_EXTENSION):
            if isinstance(p, SourceTrackingPlugin):
                self.source_tracking = p
                break

    def shutdown(self) -> None:
        self.storage = None

    # === PreprocessPluginInterface ===

    def preprocess(self, text: str, ctx: Any) -> str:
        metadata = getattr(ctx, "metadata", {}) or {}
        doc_id = metadata.get("doc_id")
        chunk_id = metadata.get("chunk_id")
        if not (doc_id and chunk_id):
            return text  # 无文档上下文 → 无需去重

        content_hash = hashlib.sha256(text.encode("utf-8")).hexdigest()
        if self._already_ingested(doc_id, chunk_id, content_hash):
            ctx.skip = True
            return text

        # 为下游附加暂存 Source（在 ctx.metadata 中）。标记写入推迟到块成功落盘之后
        # （由写入管线在阶段 ⑦ 后调用 ``record_ingested``），保证"标记已摄入 ⇔ 节点已提交"。
        section_title = metadata.get("section_title")
        metadata["_pending_source"] = Source(
            doc_id=doc_id,
            chunk_id=chunk_id,
            content_hash=content_hash,
            section_title=section_title,
        )
        return text

    # === 公共：成功落盘后标记（mark-on-success）===

    def record_ingested(
        self, doc_id: str, chunk_id: str, content_hash: str
    ) -> None:
        """把 ``(doc_id, chunk_id, content_hash)`` 记入 ``document_chunks`` 并提交。

        仅应在该块的节点成功持久化之后调用（见 ``WritePipeline``），从而出错/中断
        未落盘的块不会被标记完成、续跑会重试。
        """
        conn = getattr(self.storage, "conn", None)
        if conn is None:
            return
        conn.execute(
            "INSERT OR REPLACE INTO document_chunks "
            "(doc_id, chunk_id, content_hash) VALUES (?, ?, ?)",
            (doc_id, chunk_id, content_hash),
        )
        conn.commit()

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


def _get(obj: Any, attr: str, default: Any = None) -> Any:
    """从字典或对象属性中读取 ``attr``。"""
    if isinstance(obj, dict):
        return obj.get(attr, default)
    return getattr(obj, attr, default)

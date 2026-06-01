"""持久化测试：序列化保真 round-trip、向后兼容、提交时序、idempotency mark-on-success。

覆盖 tasks 5.3 / 5.4 / 5.5 / 5.6。
"""

from __future__ import annotations

import json
import sqlite3

from mcs.core.config import MCSConfig
from mcs.core.decisions import ConceptDraft, Decision
from mcs.core.graph import GraphStore, Node
from mcs.core.plugin_manager import PluginContext, PluginManager
from mcs.core.query_engine import QueryEngine
from mcs.core.token_budget import TokenBudget
from mcs.core.write_pipeline import WritePipeline
from mcs.plugins.phase1.source_tracking import (
    IdempotencyCheckPlugin,
    Source,
    SourceTrackingPlugin,
    _coerce_source,
)
from mcs.plugins.phase1.sqlite_storage import SQLiteStoragePlugin

# ─── 测试装配 ─────────────────────────────────────────────────────────────────


def _storage_with_source_tracking(db_path: str):
    """SQLiteStoragePlugin + SourceTrackingPlugin，已 initialize。"""
    pm = PluginManager()
    storage = SQLiteStoragePlugin({"path": db_path})
    st = SourceTrackingPlugin()
    pm.register(storage)
    pm.register(st)
    ctx = PluginContext(
        graph=GraphStore(),
        config=MCSConfig(),
        token_budget=TokenBudget(8000),
        context_renderer=None,  # type: ignore[arg-type]
        plugin_manager=pm,
    )
    pm.initialize_all(ctx)
    return storage, st, pm


def _full_pipeline(db_path: str, mock_llm):
    """完整写入管线：sqlite + source_tracking + idempotency + mock LLM。"""
    graph = GraphStore()
    pm = PluginManager()
    storage = SQLiteStoragePlugin({"path": db_path})
    st = SourceTrackingPlugin()
    idem = IdempotencyCheckPlugin()
    pm.register(mock_llm)
    pm.register(storage)
    pm.register(st)
    pm.register(idem)
    config = MCSConfig(auto_persist=True)
    ctx = PluginContext(
        graph=graph,
        config=config,
        token_budget=TokenBudget(8000),
        context_renderer=None,  # type: ignore[arg-type]
        plugin_manager=pm,
    )
    pm.initialize_all(ctx)
    qe = QueryEngine(
        graph=graph,
        llm=mock_llm,
        plugin_manager=pm,
        token_budget=TokenBudget(8000),
        max_rounds=1,
        max_picked=20,
    )
    wp = WritePipeline(
        graph=graph,
        llm=mock_llm,
        query_engine=qe,
        plugin_manager=pm,
        token_budget=TokenBudget(8000),
        config=config,
    )
    return wp, storage, idem, pm


def _set_create_decision(mock_llm, name: str):
    concept = ConceptDraft(name=name, content="content")
    mock_llm.set_response("extract_concepts", [concept])
    mock_llm.set_response(
        "judge_relations",
        [Decision(action="create", concept=concept, edges_to=[])],
    )


# ─── 5.3 序列化保真 round-trip ────────────────────────────────────────────────


def test_roundtrip_source_is_structured_not_string(tmp_path):
    storage, _st, _pm = _storage_with_source_tracking(str(tmp_path / "g.db"))
    node = Node(
        id="n1",
        name="N",
        content="c",
        extensions={
            "source_tracking": {
                "sources": [
                    Source(
                        doc_id="D1",
                        chunk_id="0",
                        content_hash="h",
                        section_title="T",
                    )
                ]
            }
        },
    )
    storage.save_node(node)
    storage.commit()

    loaded = storage.load().get_node("n1")
    sources = loaded.extensions["source_tracking"]["sources"]
    assert sources
    s0 = sources[0]
    assert not isinstance(s0, str)  # 不是 "Source(...)" 字符串
    doc_id = s0.doc_id if hasattr(s0, "doc_id") else s0["doc_id"]
    assert doc_id == "D1"


def test_roundtrip_dump_contains_dict_not_repr(tmp_path):
    """落盘的 extensions_json 中 source 是 dict，而非 default=str 的 repr 字符串。"""
    storage, _st, _pm = _storage_with_source_tracking(str(tmp_path / "g.db"))
    node = Node(
        id="n1",
        name="N",
        content="c",
        extensions={
            "source_tracking": {
                "sources": [Source(doc_id="D1", chunk_id="0", content_hash="h")]
            }
        },
    )
    storage.save_node(node)
    storage.commit()
    raw = storage.conn.execute(
        "SELECT extensions_json FROM nodes WHERE id='n1'"
    ).fetchone()[0]
    parsed = json.loads(raw)
    src0 = parsed["source_tracking"]["sources"][0]
    assert isinstance(src0, dict)
    assert src0["doc_id"] == "D1"


# ─── 5.4 向后兼容历史字符串化 Source ──────────────────────────────────────────


def test_coerce_stringified_source_recovers_doc_id():
    s = "Source(doc_id='OldDoc', chunk_id='2', content_hash='abc', section_title='Sec')"
    src = _coerce_source(s)
    assert src.doc_id == "OldDoc"
    assert src.chunk_id == "2"
    assert src.content_hash == "abc"
    assert src.section_title == "Sec"


def test_coerce_stringified_source_with_apostrophe_title():
    """标题含单引号时 repr 用双引号包裹，仍能解析出 doc_id。"""
    s = "Source(doc_id=\"Apple's Earnings\", chunk_id='0', content_hash='h', section_title=None)"
    src = _coerce_source(s)
    assert src.doc_id == "Apple's Earnings"
    assert src.section_title is None


def test_load_tolerates_legacy_stringified_source(tmp_path):
    """load() 遇到历史字符串化 source 仍能还原 doc_id（既有 db 无需重建）。"""
    storage, _st, _pm = _storage_with_source_tracking(str(tmp_path / "g.db"))
    legacy = {
        "source_tracking": {
            "sources": [
                "Source(doc_id='OldDoc', chunk_id='2', content_hash='abc', section_title='Sec')"
            ]
        }
    }
    storage.conn.execute(
        "INSERT OR REPLACE INTO nodes (id, name, content, role, extensions_json) "
        "VALUES (?, ?, ?, ?, ?)",
        ("old1", "Old", "c", "concept", json.dumps(legacy)),
    )
    storage.commit()

    s0 = storage.load().get_node("old1").extensions["source_tracking"]["sources"][0]
    doc_id = s0.doc_id if hasattr(s0, "doc_id") else s0["doc_id"]
    assert doc_id == "OldDoc"


# ─── 5.5 提交时序 ─────────────────────────────────────────────────────────────


def test_commit_visible_to_independent_connection(tmp_path):
    db = str(tmp_path / "g.db")
    storage, _st, _pm = _storage_with_source_tracking(db)
    storage.save_node(Node(id="n1", name="N", content="c"))
    storage.commit()

    other = sqlite3.connect(db)
    row = other.execute("SELECT id FROM nodes WHERE id='n1'").fetchone()
    other.close()
    assert row is not None and row[0] == "n1"


def test_ingest_commits_so_independent_reader_sees_node(tmp_path, mock_llm):
    """每次 ingest 后提交：另一个独立连接能读到刚摄入的节点。"""
    db = str(tmp_path / "g.db")
    wp, _storage, _idem, _pm = _full_pipeline(db, mock_llm)
    _set_create_decision(mock_llm, "FreshNode")
    ctx = wp.ingest("text", doc_id="D1", chunk_id="0")
    assert ctx.persisted is True

    other = sqlite3.connect(db)
    cnt = other.execute("SELECT COUNT(*) FROM nodes").fetchone()[0]
    other.close()
    assert cnt >= 1


def test_shutdown_does_not_lose_last_chunk(tmp_path, mock_llm):
    """连续 ingest 后 shutdown，最后一块的节点仍已提交持久化。"""
    db = str(tmp_path / "g.db")
    wp, _storage, _idem, pm = _full_pipeline(db, mock_llm)
    _set_create_decision(mock_llm, "LastChunkNode")
    wp.ingest("text", doc_id="D1", chunk_id="0")
    pm.shutdown_all()  # 关闭连接

    storage2, _st2, _pm2 = _storage_with_source_tracking(db)
    names = [n.name for n in storage2.load().get_all_nodes()]
    assert "LastChunkNode" in names


# ─── 5.6 idempotency mark-on-success ──────────────────────────────────────────


def test_success_marks_chunk_and_second_ingest_skips(tmp_path, mock_llm):
    db = str(tmp_path / "g.db")
    wp, storage, _idem, _pm = _full_pipeline(db, mock_llm)
    _set_create_decision(mock_llm, "X")

    ctx = wp.ingest("text", doc_id="D1", chunk_id="0")
    assert ctx.persisted is True
    row = storage.conn.execute(
        "SELECT content_hash FROM document_chunks WHERE doc_id='D1' AND chunk_id='0'"
    ).fetchone()
    assert row is not None  # 成功落盘后才标记

    ctx2 = wp.ingest("text", doc_id="D1", chunk_id="0")
    assert ctx2.skip is True  # 已标记 → 续跑短路


def test_failed_persist_not_marked_and_retried(tmp_path, mock_llm):
    db = str(tmp_path / "g.db")
    wp, storage, _idem, _pm = _full_pipeline(db, mock_llm)
    _set_create_decision(mock_llm, "X")

    # 模拟落盘失败：save_node 抛异常
    orig_save = storage.save_node

    def boom(node):
        raise RuntimeError("disk full")

    storage.save_node = boom  # type: ignore[method-assign]
    ctx = wp.ingest("text", doc_id="D1", chunk_id="0")
    assert ctx.persisted is False
    row = storage.conn.execute(
        "SELECT * FROM document_chunks WHERE doc_id='D1' AND chunk_id='0'"
    ).fetchone()
    assert row is None  # 出错的块未被标记

    # 恢复存储 → 续跑应重试该块（不被跳过），这次成功落盘并标记
    storage.save_node = orig_save  # type: ignore[method-assign]
    ctx2 = wp.ingest("text", doc_id="D1", chunk_id="0")
    assert ctx2.skip is False
    assert ctx2.persisted is True
    row2 = storage.conn.execute(
        "SELECT * FROM document_chunks WHERE doc_id='D1' AND chunk_id='0'"
    ).fetchone()
    assert row2 is not None

"""持久化测试：序列化保真 round-trip、向后兼容、提交时序、idempotency mark-on-success。

覆盖 tasks 5.3 / 5.4 / 5.5 / 5.6。
"""

from __future__ import annotations

import hashlib
import json
import sqlite3

from mcs.core.config import MCSConfig
from mcs.core.decisions import ConceptDraft, Decision
from mcs.core.graph import Node
from mcs.core.plugin_manager import PluginContext, PluginManager
from mcs.core.query_engine import QueryEngine
from mcs.core.token_budget import TokenBudget
from mcs.core.write_pipeline import WritePipeline
from mcs.plugins.preprocess.source_tracking import (
    IdempotencyCheckPlugin,
    Source,
    SourceTrackingPlugin,
    _coerce_source,
)
from mcs.stores.in_memory import InMemoryStore
from mcs.stores.sqlite_store import SQLiteStore

GraphStore = InMemoryStore

# ─── 测试装配 ─────────────────────────────────────────────────────────────────


def _storage_with_source_tracking(db_path: str):
    """SQLiteStore + SourceTrackingPlugin，已 initialize。"""
    pm = PluginManager()
    store = SQLiteStore({"path": db_path})
    st = SourceTrackingPlugin()
    pm.register(st)
    store.initialize(
        schema_extensions=[st],  # SourceTrackingPlugin 实现 StorageSchemaExtensionInterface
        node_extensions={"source_tracking": st},
    )
    ctx = PluginContext(
        store=store,
        config=MCSConfig(),
        token_budget=TokenBudget(8000),
        context_renderer=None,  # type: ignore[arg-type]
        plugin_manager=pm,
    )
    pm.initialize_all(ctx)
    return store, st, pm


def test_save_full_reflects_edge_deletion(tmp_path):
    """save_full 全量重建：被删除的边在持久化后消失（增量 save 做不到）。"""
    db = str(tmp_path / "sf.db")
    store, _st, _pm = _storage_with_source_tracking(db)
    store.add_node(Node(id="a", name="A", content=""))
    store.add_node(Node(id="b", name="B", content=""))
    store.add_edge("a", "b")
    store.save()              # 增量存：a、b、边 a-b
    store.delete_edge("a", "b")     # 内存删边
    store.save_full()        # 全量重建应反映删除

    store2 = SQLiteStore({"path": db})
    store2.initialize()
    store2.load()
    assert store2.get_node("a") is not None
    assert store2.get_node("b") is not None
    assert store2.get_edge("a", "b") is None  # 边已不在持久存储


def test_incremental_save_does_not_delete_edge(tmp_path):
    """对照：增量 save 只 upsert、不删行 —— 这正是需要 save_full 的原因。"""
    db = str(tmp_path / "sf2.db")
    store, _st, _pm = _storage_with_source_tracking(db)
    store.add_node(Node(id="a", name="A", content=""))
    store.add_node(Node(id="b", name="B", content=""))
    store.add_edge("a", "b")
    store.save()
    store.delete_edge("a", "b")
    store.save()             # 增量再存：不会删除旧边

    store2 = SQLiteStore({"path": db})
    store2.initialize()
    store2.load()
    assert store2.get_edge("a", "b") is not None  # 旧边仍在 → 故需 save_full


def test_flush_changes_persists_seed_root_incrementally(tmp_path):
    """回归：flush_changes 让虚拟根节点 + 其有向层级边增量落盘（不调用 save_full）。

    曾经 __seed_root__ 与 root→concept 边只在 save_full 落库，增量持久化抓不到；
    <save_full 节奏的小图或中断续跑会重载出无根图、根边丢失。
    """
    db = str(tmp_path / "root.db")
    store = SQLiteStore({"path": db})
    store.initialize()
    store.add_node(Node(id="__seed_root__", name="__seed_root__", content="", role="hub"))
    store.add_node(Node(id="c1", name="C1", content="概念一"))
    store.add_node(Node(id="c2", name="C2", content="概念二"))
    store.add_edge("__seed_root__", "c1")
    store.add_edge("__seed_root__", "c2")
    store.flush_changes()  # 增量落盘——注意未调用 save_full
    store.shutdown()

    store2 = SQLiteStore({"path": db})
    store2.initialize()
    store2.load()
    root = store2.get_node("__seed_root__")
    assert root is not None and root.role == "hub"
    assert store2.get_edge("__seed_root__", "c1") is not None
    assert store2.get_edge("__seed_root__", "c2") is not None


def test_flush_changes_reflects_edge_deletion_incrementally(tmp_path):
    """回归：flush_changes 增量反映边删除（重挂）——save() 做不到、过去依赖 save_full。"""
    db = str(tmp_path / "rehang.db")
    store = SQLiteStore({"path": db})
    store.initialize()
    for nid in ("__seed_root__", "c1", "hub1"):
        store.add_node(Node(id=nid, name=nid, content=""))
    store.add_edge("__seed_root__", "c1")
    store.flush_changes()
    # 重挂：删 root→c1，新增 root→hub1 与 hub1→c1
    store.delete_edge("__seed_root__", "c1")
    store.add_edge("__seed_root__", "hub1")
    store.add_edge("hub1", "c1")
    store.flush_changes()
    store.shutdown()

    store2 = SQLiteStore({"path": db})
    store2.initialize()
    store2.load()
    assert store2.get_edge("__seed_root__", "c1") is None  # 旧边已被增量删除
    assert store2.get_edge("__seed_root__", "hub1") is not None
    assert store2.get_edge("hub1", "c1") is not None


def test_flush_changes_reflects_node_deletion_incrementally(tmp_path):
    """回归：flush_changes 增量反映节点删除（如合并同义删成员）及其级联删边。"""
    db = str(tmp_path / "del.db")
    store = SQLiteStore({"path": db})
    store.initialize()
    store.add_node(Node(id="a", name="A", content=""))
    store.add_node(Node(id="b", name="B", content=""))
    store.add_edge("a", "b")
    store.flush_changes()
    store.delete_node("b")  # 级联删 a→b 边
    store.flush_changes()
    store.shutdown()

    store2 = SQLiteStore({"path": db})
    store2.initialize()
    store2.load()
    assert store2.get_node("b") is None
    assert store2.get_edge("a", "b") is None


def test_reorg_rollback_no_duplicate_edges_after_flush(tmp_path):
    """回归：fanout 裂变回滚 + 增量持久化不留重复边。

    旧 _rollback_reorg 用 add_edge 重建（生成新 uuid + 绕过删除跟踪），
    使旧持久化行残留、新行又插入 → 每条边在 DB 翻倍，reload 后 get_facts 重复。
    新实现走 store.restore（保留边 id + 还原变更跟踪集），DB 边数不变。
    """
    from mcs.plugins.maintenance.fanout_reducer import FanoutReducerPlugin

    db = str(tmp_path / "rollback.db")
    store = SQLiteStore({"path": db})
    store.initialize()
    for nid in ["a", "b", "c", "d"]:
        store.add_node(Node(id=nid, name=nid, content=nid))
    store.add_edge("a", "b", kind="fact", label="likes")
    store.add_edge("a", "c", kind="hierarchy")
    store.add_edge("a", "d", kind="hierarchy")
    store.flush_changes()  # 模拟上一轮 ingest 增量落盘（3 条边）

    plugin = FanoutReducerPlugin()
    snap = store.snapshot()
    # 模拟一次中途修改后被判定失败、需回滚的 reorg：
    store.add_node(Node(id="hub", name="hub", content="hub", role="hub"))
    store.add_edge("hub", "b", kind="hierarchy")
    ac_id = next(e.id for e in store.get_edges_between("a", "c"))
    store.delete_edge(ac_id)
    plugin._rollback_reorg(store, snap)

    # 回滚后内存图应已复原（3 条边、无 hub）
    assert len(store.get_all_edges()) == 3
    assert store.get_node("hub") is None

    store.flush_changes()  # 下一轮 ingest 的 stage⑦
    store.shutdown()

    # 全新进程 reload：DB 不应有重复边
    store2 = SQLiteStore({"path": db})
    store2.initialize()
    store2.load()
    assert len(store2.get_all_edges()) == 3, "回滚后 DB 出现重复边"
    assert len(store2.get_facts("a")) == 1
    assert len(store2.get_edges_between("a", "c")) == 1
    assert store2.get_node("hub") is None


def test_store_snapshot_restore_roundtrip_preserves_edge_ids(tmp_path):
    """snapshot/restore round-trip 保留边 id 与 label（InMemory + SQLite 同契约）。"""
    for store in (InMemoryStore(), SQLiteStore({"path": str(tmp_path / "snap.db")})):
        if isinstance(store, SQLiteStore):
            store.initialize()
        store.add_node(Node(id="a", name="A", content="A"))
        store.add_node(Node(id="b", name="B", content="B"))
        fid = store.add_edge("a", "b", kind="fact", label="喜欢")
        snap = store.snapshot()
        store.delete_edge(fid)
        store.add_edge("a", "b", kind="fact", label="讨厌")
        store.restore(snap)
        facts = store.get_facts("a")
        assert len(facts) == 1
        assert facts[0].id == fid
        assert facts[0].label == "喜欢"


def _full_pipeline(db_path: str, mock_llm):
    """完整写入管线：SQLiteStore + source_tracking + idempotency + mock LLM。"""
    store = SQLiteStore({"path": db_path})
    pm = PluginManager()
    st = SourceTrackingPlugin()
    idem = IdempotencyCheckPlugin()
    pm.register(mock_llm)
    pm.register(st)
    pm.register(idem)
    config = MCSConfig(auto_persist=True)
    store.initialize(
        schema_extensions=[st],  # SourceTrackingPlugin 实现 StorageSchemaExtensionInterface
        node_extensions={"source_tracking": st},
    )
    ctx = PluginContext(
        store=store,
        config=config,
        token_budget=TokenBudget(8000),
        context_renderer=None,  # type: ignore[arg-type]
        plugin_manager=pm,
    )
    pm.initialize_all(ctx)
    qe = QueryEngine(
        store=store,
        llm=mock_llm,
        plugin_manager=pm,
        token_budget=TokenBudget(8000),
        max_rounds=1,
        max_accumulated_nodes=20,
    )
    wp = WritePipeline(
        store=store,
        llm=mock_llm,
        query_engine=qe,
        plugin_manager=pm,
        token_budget=TokenBudget(8000),
        config=config,
    )
    return wp, store, idem, pm


def _set_create_decision(mock_llm, name: str):
    concept = ConceptDraft(name=name, content="content")
    mock_llm.set_response("extract_concepts", [concept])
    mock_llm.set_response(
        "judge_relations",
        [Decision(action="create", concept=concept, edges_to=[])],
    )


# ─── 5.3 序列化保真 round-trip ────────────────────────────────────────────────


def test_roundtrip_source_is_structured_not_string(tmp_path):
    store, _st, _pm = _storage_with_source_tracking(str(tmp_path / "g.db"))
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
    store.add_node(node)
    store._save_node(node)
    store.commit()

    store2 = SQLiteStore({"path": str(tmp_path / "g.db")})
    store2.initialize()
    store2.load()
    loaded = store2.get_node("n1")
    sources = loaded.extensions["source_tracking"]["sources"]
    assert sources
    s0 = sources[0]
    assert not isinstance(s0, str)  # 不是 "Source(...)" 字符串
    doc_id = s0.doc_id if hasattr(s0, "doc_id") else s0["doc_id"]
    assert doc_id == "D1"


def test_roundtrip_dump_contains_dict_not_repr(tmp_path):
    """落盘的 extensions_json 中 source 是 dict，而非 default=str 的 repr 字符串。"""
    store, _st, _pm = _storage_with_source_tracking(str(tmp_path / "g.db"))
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
    store.add_node(node)
    store._save_node(node)
    store.commit()
    raw = store.conn.execute(
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
    db_path = str(tmp_path / "g.db")
    store, _st, _pm = _storage_with_source_tracking(db_path)
    legacy = {
        "source_tracking": {
            "sources": [
                "Source(doc_id='OldDoc', chunk_id='2', content_hash='abc', section_title='Sec')"
            ]
        }
    }
    store.conn.execute(
        "INSERT OR REPLACE INTO nodes (id, name, content, role, extensions_json) "
        "VALUES (?, ?, ?, ?, ?)",
        ("old1", "Old", "c", "concept", json.dumps(legacy)),
    )
    store.commit()

    # 新 store 需要 SourceTrackingPlugin 作为 node_extension 才能反序列化
    st2 = SourceTrackingPlugin()
    store2 = SQLiteStore({"path": db_path})
    store2.initialize(
        schema_extensions=[st2],
        node_extensions={"source_tracking": st2},
    )
    store2.load()
    s0 = store2.get_node("old1").extensions["source_tracking"]["sources"][0]
    doc_id = s0.doc_id if hasattr(s0, "doc_id") else s0["doc_id"]
    assert doc_id == "OldDoc"


# ─── 5.5 提交时序 ─────────────────────────────────────────────────────────────


def test_commit_visible_to_independent_connection(tmp_path):
    db = str(tmp_path / "g.db")
    store, _st, _pm = _storage_with_source_tracking(db)
    store.add_node(Node(id="n1", name="N", content="c"))
    store._save_node(store.get_node("n1"))
    store.commit()

    other = sqlite3.connect(db)
    row = other.execute("SELECT id FROM nodes WHERE id='n1'").fetchone()
    other.close()
    assert row is not None and row[0] == "n1"


def test_ingest_commits_so_independent_reader_sees_node(tmp_path, mock_llm):
    """每次 ingest 后提交：另一个独立连接能读到刚摄入的节点。"""
    db = str(tmp_path / "g.db")
    wp, _store, _idem, _pm = _full_pipeline(db, mock_llm)
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
    wp, store, _idem, pm = _full_pipeline(db, mock_llm)
    _set_create_decision(mock_llm, "LastChunkNode")
    wp.ingest("text", doc_id="D1", chunk_id="0")
    pm.shutdown_all()  # 关闭连接
    store.shutdown()

    store2, _st2, _pm2 = _storage_with_source_tracking(db)
    store2.load()
    names = [n.name for n in store2.get_all_nodes()]
    assert "LastChunkNode" in names


# ─── 5.6 idempotency mark-on-success ──────────────────────────────────────────


def test_success_marks_chunk_and_second_ingest_is_idempotent(tmp_path, mock_llm):
    db = str(tmp_path / "g.db")
    wp, store, idem, _pm = _full_pipeline(db, mock_llm)
    _set_create_decision(mock_llm, "X")

    ctx = wp.ingest("text", doc_id="D1", chunk_id="0")
    assert ctx.persisted is True
    row = store.conn.execute(
        "SELECT content_hash FROM document_chunks WHERE doc_id='D1' AND chunk_id='0'"
    ).fetchone()
    assert row is not None  # 成功落盘后才标记

    # 调用方通过 is_ingested() 判断是否跳过，不再进入管线
    content_hash = hashlib.sha256("text".encode("utf-8")).hexdigest()
    assert idem.is_ingested("D1", "0", content_hash) is True


def test_failed_persist_not_marked_and_retried(tmp_path, mock_llm):
    db = str(tmp_path / "g.db")
    wp, store, idem, _pm = _full_pipeline(db, mock_llm)
    _set_create_decision(mock_llm, "X")

    # 模拟落盘失败：save_node 抛异常
    orig_save = store._save_node

    def boom(node):
        raise RuntimeError("disk full")

    store._save_node = boom  # type: ignore[method-assign]
    ctx = wp.ingest("text", doc_id="D1", chunk_id="0")
    assert ctx.persisted is False
    row = store.conn.execute(
        "SELECT * FROM document_chunks WHERE doc_id='D1' AND chunk_id='0'"
    ).fetchone()
    assert row is None  # 出错的块未被标记

    # 恢复存储 → 续跑应重试该块（is_ingested 返回 False），这次成功落盘并标记
    store._save_node = orig_save  # type: ignore[method-assign]
    content_hash = hashlib.sha256("text".encode("utf-8")).hexdigest()
    assert idem.is_ingested("D1", "0", content_hash) is False
    ctx2 = wp.ingest("text", doc_id="D1", chunk_id="0")
    assert ctx2.persisted is True
    row2 = store.conn.execute(
        "SELECT * FROM document_chunks WHERE doc_id='D1' AND chunk_id='0'"
    ).fetchone()
    assert row2 is not None
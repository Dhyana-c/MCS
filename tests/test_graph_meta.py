"""store 图级元数据 kv 原语测试（graph-summary change，task 1.5）。

覆盖 ``StoreInterface.get_graph_meta`` / ``set_graph_meta`` 的 InMemoryStore 与
SQLiteStore 实现：CRUD、set 覆盖、缺 key 返回 None、SQLiteStore 跨实例 round-trip
保真、图级 meta 与节点字段隔离。
"""

from __future__ import annotations

from mcs.stores.in_memory import InMemoryStore
from mcs.stores.sqlite_store import SQLiteStore


# === InMemoryStore ===


def test_inmemory_get_missing_returns_none():
    assert InMemoryStore().get_graph_meta("absent") is None


def test_inmemory_set_then_get():
    store = InMemoryStore()
    store.set_graph_meta("graph_summary", "X")
    assert store.get_graph_meta("graph_summary") == "X"


def test_inmemory_set_overwrites():
    store = InMemoryStore()
    store.set_graph_meta("graph_summary", "old")
    store.set_graph_meta("graph_summary", "new")
    assert store.get_graph_meta("graph_summary") == "new"


def test_inmemory_meta_isolated_from_nodes():
    """图级 meta 非节点字段：写入不落到任何节点的 extensions。"""
    store = InMemoryStore()
    store.set_graph_meta("graph_summary", "S")
    assert all(
        "graph_summary" not in (n.extensions or {}) for n in store.get_all_nodes()
    )


# === SQLiteStore ===


def test_sqlite_get_missing_returns_none(tmp_path):
    store = SQLiteStore({"path": str(tmp_path / "t.db")})
    store.initialize()
    assert store.get_graph_meta("absent") is None


def test_sqlite_set_then_get(tmp_path):
    store = SQLiteStore({"path": str(tmp_path / "t.db")})
    store.initialize()
    store.set_graph_meta("graph_summary", "X")
    assert store.get_graph_meta("graph_summary") == "X"


def test_sqlite_set_overwrites(tmp_path):
    store = SQLiteStore({"path": str(tmp_path / "t.db")})
    store.initialize()
    store.set_graph_meta("graph_summary", "old")
    store.set_graph_meta("graph_summary", "new")
    assert store.get_graph_meta("graph_summary") == "new"


def test_sqlite_roundtrip_after_reload(tmp_path):
    """set → 新实例 load → get 命中（meta 经 SQLite 持久化，跨实例保真）。"""
    db = str(tmp_path / "t.db")
    s1 = SQLiteStore({"path": db})
    s1.initialize()
    s1.set_graph_meta("graph_summary", "persisted")
    s1.set_graph_meta("other", "v")

    s2 = SQLiteStore({"path": db})
    s2.initialize()
    s2.load()
    assert s2.get_graph_meta("graph_summary") == "persisted"
    assert s2.get_graph_meta("other") == "v"

"""方向感知图原语测试：out 边邻接、out vs all 邻居视图、持久化 round-trip 方向保真。

覆盖 seed-graph-directional-hierarchy 任务 1.3 / 1.4。
"""

from __future__ import annotations

import tempfile

from mcs.core.graph import Edge, GraphStore, Node
from mcs.plugins.phase1.sqlite_storage import SQLiteStoragePlugin


def test_add_edge_out_is_unidirectional():
    """out 边：source 能看到 target，但 target 不能看到 source。"""
    g = GraphStore()
    g.add_node(Node(id="a", name="A", content=""))
    g.add_node(Node(id="b", name="B", content=""))
    g.add_edge("a", "b", direction="out")

    # source a 能看到 target b
    assert {n.id for n in g.get_neighbors("a")} == {"b"}
    # target b 不能看到 source a（单向）
    assert {n.id for n in g.get_neighbors("b")} == set()


def test_add_edge_bidirectional_is_symmetric():
    """bidirectional 边：两端互为邻居。"""
    g = GraphStore()
    g.add_node(Node(id="a", name="A", content=""))
    g.add_node(Node(id="b", name="B", content=""))
    g.add_edge("a", "b", direction="bidirectional")

    assert {n.id for n in g.get_neighbors("a")} == {"b"}
    assert {n.id for n in g.get_neighbors("b")} == {"a"}


def test_get_out_neighbors_only_returns_out_targets():
    """get_out_neighbors 只返回 direction=out 的边目标，不含 bidirectional 邻居。"""
    g = GraphStore()
    g.add_node(Node(id="a", name="A", content=""))
    g.add_node(Node(id="b", name="B", content=""))
    g.add_node(Node(id="c", name="C", content=""))
    g.add_node(Node(id="x", name="X", content=""))

    g.add_edge("a", "b", direction="out")      # a→b 有向下行
    g.add_edge("a", "c", direction="out")      # a→c 有向下行
    g.add_edge("a", "x", direction="bidirectional")  # a↔x 语义双向

    # get_neighbors（全部邻居）：b, c, x
    assert {n.id for n in g.get_neighbors("a")} == {"b", "c", "x"}
    # get_out_neighbors（仅 out）：b, c（不含 x）
    assert {n.id for n in g.get_out_neighbors("a")} == {"b", "c"}


def test_get_out_neighbors_empty_when_no_out_edges():
    """只有 bidirectional 边时，get_out_neighbors 返回空。"""
    g = GraphStore()
    g.add_node(Node(id="a", name="A", content=""))
    g.add_node(Node(id="b", name="B", content=""))
    g.add_edge("a", "b", direction="bidirectional")

    assert g.get_out_neighbors("a") == []
    assert g.get_out_neighbors("b") == []


def test_target_of_out_edge_has_no_out_neighbors_from_source():
    """a→b（out）时，b 的 out_neighbors 不含 a。"""
    g = GraphStore()
    g.add_node(Node(id="a", name="A", content=""))
    g.add_node(Node(id="b", name="B", content=""))
    g.add_edge("a", "b", direction="out")

    assert g.get_out_neighbors("b") == []


def test_save_load_roundtrip_preserves_out_direction():
    """save_full → load：out 边方向保真。"""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    g = GraphStore()
    g.add_node(Node(id="a", name="A", content=""))
    g.add_node(Node(id="b", name="B", content=""))
    g.add_node(Node(id="c", name="C", content=""))
    g.add_edge("a", "b", direction="out")
    g.add_edge("b", "c", direction="bidirectional")

    storage = SQLiteStoragePlugin({"path": db_path})
    storage.conn = None  # 先 shutdown
    # 手动初始化（模拟 initialize）
    import sqlite3
    storage.conn = sqlite3.connect(db_path)
    storage._create_tables([])

    storage.save_full(g)
    storage.commit()

    loaded = storage.load()

    # out 边 a→b 方向保真
    edge_ab = loaded.get_edge("a", "b")
    assert edge_ab is not None
    assert edge_ab.direction == "out"

    # bidirectional 边 b↔c 方向保真
    edge_bc = loaded.get_edge("b", "c")
    assert edge_bc is not None
    assert edge_bc.direction == "bidirectional"

    # 验证邻接关系：out 边只有单向，bidirectional 双向
    assert {n.id for n in loaded.get_neighbors("a")} == {"b"}
    assert {n.id for n in loaded.get_neighbors("b")} == {"c"}  # 只有 bidirectional 的 c
    assert {n.id for n in loaded.get_neighbors("c")} == {"b"}

    storage.shutdown()

    import os
    os.unlink(db_path)


def test_mixed_direction_edges_coexist():
    """不同节点对可混合 out / bidirectional 边，各自方向保真。"""
    g = GraphStore()
    g.add_node(Node(id="a", name="A", content=""))
    g.add_node(Node(id="b", name="B", content=""))
    g.add_node(Node(id="c", name="C", content=""))

    g.add_edge("a", "b", direction="out")
    g.add_edge("a", "c", direction="bidirectional")
    g.add_edge("b", "c", direction="out")

    # 各边各自方向保真
    assert g.get_edge("a", "b").direction == "out"
    assert g.get_edge("a", "c").direction == "bidirectional"
    assert g.get_edge("b", "c").direction == "out"

    # a 的邻居：b（out）+ c（bidirectional）
    assert {n.id for n in g.get_neighbors("a")} == {"b", "c"}
    # a 的 out 邻居：只有 b
    assert {n.id for n in g.get_out_neighbors("a")} == {"b"}


def test_same_pair_out_and_bidirectional_coexist():
    """同一对节点可同时持有 out 与 bidirectional 边（内存键含 direction，与 DB 主键对齐）。

    覆盖边键加固：修复前 a→b(out) 会被已存在的 a↔b(bidi) 静默挡掉（key 冲突）。
    """
    g = GraphStore()
    g.add_node(Node(id="a", name="A", content=""))
    g.add_node(Node(id="b", name="B", content=""))
    g.add_edge("a", "b", direction="bidirectional")
    g.add_edge("a", "b", direction="out")

    triples = {(e.source_id, e.target_id, e.direction) for e in g.get_all_edges()}
    assert ("a", "b", "bidirectional") in triples
    assert ("a", "b", "out") in triples
    assert len(g.get_all_edges()) == 2

    # 邻接去重：a 看到 b；a 的 out 邻居含 b
    assert {n.id for n in g.get_neighbors("a")} == {"b"}
    assert {n.id for n in g.get_out_neighbors("a")} == {"b"}
    # b 经双向边看到 a，但其 out 邻居不含 a（out 边是 a→b 单向）
    assert {n.id for n in g.get_neighbors("b")} == {"a"}
    assert g.get_out_neighbors("b") == []


def test_same_pair_dual_edge_roundtrip():
    """同对节点 out + bidirectional 双边经 save_full→load 均保真、不互相覆盖。"""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    g = GraphStore()
    g.add_node(Node(id="a", name="A", content=""))
    g.add_node(Node(id="b", name="B", content=""))
    g.add_edge("a", "b", direction="bidirectional")
    g.add_edge("a", "b", direction="out")

    import sqlite3
    storage = SQLiteStoragePlugin({"path": db_path})
    storage.conn = sqlite3.connect(db_path)
    storage._create_tables([])
    storage.save_full(g)
    storage.commit()

    loaded = storage.load()
    triples = {(e.source_id, e.target_id, e.direction) for e in loaded.get_all_edges()}
    assert ("a", "b", "bidirectional") in triples
    assert ("a", "b", "out") in triples
    assert len(loaded.get_all_edges()) == 2

    storage.shutdown()
    import os
    os.unlink(db_path)
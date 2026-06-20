"""单向有向边图原语测试：add_edge(a,b) 仅 source→target、邻接查询、持久化 round-trip。

覆盖 unidirectional-edge 模型：
  - add_edge(source, target) 无 direction 参数，边为单向 source→target
  - get_out_hierarchy 只返回出边目标
  - Edge dataclass 只有 source_id / target_id，无 direction 字段
  - SQLite schema 边表为 (source_id, target_id)，无 direction 列
"""

from __future__ import annotations

import os
import tempfile

from mcs.entities.graph import Edge, Node
from mcs.stores.in_memory import InMemoryStore
from mcs.stores.sqlite_store import SQLiteStore

GraphStore = InMemoryStore


def test_add_edge_is_unidirectional():
    """add_edge(a, b) 使 a 看到 b，但 b 不能看到 a。"""
    g = GraphStore()
    g.add_node(Node(id="a", name="A", content=""))
    g.add_node(Node(id="b", name="B", content=""))
    g.add_edge("a", "b")

    # source a 能看到 target b
    assert {n.id for n in g.get_out_hierarchy("a")} == {"b"}
    # target b 不能看到 source a（单向）
    assert {n.id for n in g.get_out_hierarchy("b")} == set()


def test_get_out_hierarchy_returns_out_targets():
    """get_out_hierarchy(a) 只返回 a 作为 source 的出边目标。"""
    g = GraphStore()
    g.add_node(Node(id="a", name="A", content=""))
    g.add_node(Node(id="b", name="B", content=""))
    g.add_node(Node(id="c", name="C", content=""))

    g.add_edge("a", "b")
    g.add_edge("a", "c")
    g.add_edge("b", "c")

    # a 的出边目标是 b 和 c
    assert {n.id for n in g.get_out_hierarchy("a")} == {"b", "c"}
    # b 的出边目标是 c（不包含 a，因为 a→b 是 a 的出边）
    assert {n.id for n in g.get_out_hierarchy("b")} == {"c"}
    # c 没有出边
    assert {n.id for n in g.get_out_hierarchy("c")} == set()


def test_save_load_roundtrip():
    """边经 save_full→load round-trip 后，邻接关系正确恢复。"""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    storage = SQLiteStore({"path": db_path})
    storage.initialize()
    storage.add_node(Node(id="a", name="A", content=""))
    storage.add_node(Node(id="b", name="B", content=""))
    storage.add_node(Node(id="c", name="C", content=""))
    storage.add_edge("a", "b")
    storage.add_edge("b", "c")

    storage.save_full()

    # 加载到新 store 验证
    loaded = SQLiteStore({"path": db_path})
    loaded.initialize()
    loaded.load()

    # 边保真
    edges_ab = loaded.get_edges_between("a", "b")
    assert len(edges_ab) == 1
    edge_ab = edges_ab[0]
    assert edge_ab.source_id == "a"
    assert edge_ab.target_id == "b"

    edges_bc = loaded.get_edges_between("b", "c")
    assert len(edges_bc) == 1
    edge_bc = edges_bc[0]
    assert edge_bc.source_id == "b"
    assert edge_bc.target_id == "c"

    # 反向边不存在
    assert loaded.get_edges_between("b", "a") == []
    assert loaded.get_edges_between("c", "b") == []

    # 邻接关系：单向保真
    assert {n.id for n in loaded.get_out_hierarchy("a")} == {"b"}
    assert {n.id for n in loaded.get_out_hierarchy("b")} == {"c"}
    assert {n.id for n in loaded.get_out_hierarchy("c")} == set()

    # Edge dataclass 无 direction 字段
    assert not hasattr(edge_ab, "direction")

    storage.shutdown()
    loaded.shutdown()
    os.unlink(db_path)


def test_self_loop_ignored():
    """add_edge(a, a) 被静默忽略，不产生自环边。"""
    g = GraphStore()
    g.add_node(Node(id="a", name="A", content=""))
    g.add_edge("a", "a")

    assert g.get_edges_between("a", "a") == []
    assert g.get_out_hierarchy("a") == []


def test_duplicate_edge_ignored():
    """重复添加同一条边是幂等的，不会产生重复。"""
    g = GraphStore()
    g.add_node(Node(id="a", name="A", content=""))
    g.add_node(Node(id="b", name="B", content=""))
    g.add_edge("a", "b")
    g.add_edge("a", "b")  # 重复添加

    assert len(g.get_all_edges()) == 1
    assert {n.id for n in g.get_out_hierarchy("a")} == {"b"}


def test_opposite_edges_coexist():
    """add_edge(a, b) 与 add_edge(b, a) 是两条独立的单向边，可共存。"""
    g = GraphStore()
    g.add_node(Node(id="a", name="A", content=""))
    g.add_node(Node(id="b", name="B", content=""))
    g.add_edge("a", "b")
    g.add_edge("b", "a")

    # 两条边共存
    assert len(g.get_all_edges()) == 2
    assert g.get_edges_between("a", "b") != []
    assert g.get_edges_between("b", "a") != []

    # 双向邻接：语义双向以两条对向单向边表达
    assert {n.id for n in g.get_out_hierarchy("a")} == {"b"}
    assert {n.id for n in g.get_out_hierarchy("b")} == {"a"}

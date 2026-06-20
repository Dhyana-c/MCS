"""统一图模型（unified-graph-schema）数据结构 + 存储原语测试。

覆盖 openspec tasks #20/#21/#22：
  - Node.node_class（4 类）+ hub 标记（#20）
  - Edge.type（仅 关联/互斥）+ 登记制校验（#21）
  - store 适配：add_edge(type=)、get_relations（载重过滤）、get_out_hierarchy、SQLite schema（#22）

侧重边界：自环、未知 type、悬空端点、核心节点过滤事件边、关联/互斥去重。
"""

from __future__ import annotations

import pytest

from mcs.entities.config import MCSConfig
from mcs.entities.graph import (
    ALLOWED_EDGE_TYPES,
    CLASS_CONCEPT,
    CLASS_EVENT,
    CLASS_FACT,
    CLASS_SOURCE,
    CORE_NODE_CLASSES,
    EDGE_ASSOC,
    EDGE_MUTEX,
    NODE_CLASSES,
    Edge,
    Node,
)
from mcs.stores.in_memory import InMemoryStore
from mcs.stores.sqlite_store import SQLiteStore


# ── 数据结构默认值（#20/#21）──────────────────────────────────────────────


def test_node_defaults_concept_and_hub_false():
    """Node 默认 node_class=概念、hub=False（hub 仅为标记）。"""
    n = Node(id="x", name="n", content="c")
    assert n.node_class == CLASS_CONCEPT
    assert n.hub is False


def test_edge_defaults_assoc():
    """Edge 默认 type=关联。"""
    e = Edge(source_id="a", target_id="b")
    assert e.type == EDGE_ASSOC


def test_node_classes_registry():
    """4 类节点登记制（概念/事实/事件/source）；核心类 = 概念+事实。"""
    assert NODE_CLASSES == {CLASS_CONCEPT, CLASS_FACT, CLASS_EVENT, CLASS_SOURCE}
    assert CORE_NODE_CLASSES == {CLASS_CONCEPT, CLASS_FACT}


def test_edge_types_registry():
    """边类型登记制：仅 关联/互斥。"""
    assert ALLOWED_EDGE_TYPES == {EDGE_ASSOC, EDGE_MUTEX}


def test_config_has_no_relation_model():
    """统一模型：MCSConfig 不再持有 relation_model / attribute_content_max。"""
    cfg = MCSConfig()
    assert not hasattr(cfg, "relation_model")
    assert not hasattr(cfg, "attribute_content_max")


# ── add_node 登记制校验（node_class，对齐 Edge.type）─────────────────────


def test_add_node_rejects_unknown_node_class():
    """add_node 未知 node_class MUST 抛 ValueError（登记制，拦截旧 attribute 等）。"""
    store = InMemoryStore()
    with pytest.raises(ValueError, match="unknown node_class"):
        store.add_node(Node(id="x", name="x", content="", node_class="attribute"))


def test_update_node_rejects_unknown_node_class():
    """update_node 把 node_class 改成非法值 MUST 抛 ValueError。"""
    store = InMemoryStore()
    store.add_node(Node(id="x", name="x", content="", node_class=CLASS_CONCEPT))
    with pytest.raises(ValueError, match="unknown node_class"):
        store.update_node("x", {"node_class": "attribute"})


def test_add_node_accepts_all_registered_classes():
    """4 类登记 node_class 全部通过校验（概念/事实/事件/source）。"""
    store = InMemoryStore()
    for i, nc in enumerate([CLASS_CONCEPT, CLASS_FACT, CLASS_EVENT, CLASS_SOURCE]):
        store.add_node(Node(id=f"n{i}", name=f"n{i}", content="", node_class=nc))
    assert len(store.get_all_nodes()) == 4


def test_sqlite_add_node_rejects_unknown_node_class(tmp_path):
    """SQLiteStore.add_node 同样校验 node_class（与 InMemoryStore 对称）。"""
    store = SQLiteStore({"path": str(tmp_path / "g.db")})
    store.initialize()
    with pytest.raises(ValueError, match="unknown node_class"):
        store.add_node(Node(id="x", name="x", content="", node_class="attribute"))


# ── add_edge 登记制校验 + 边界（#21/#22）──────────────────────────────────


def test_add_edge_rejects_unknown_type():
    """add_edge 未知 type MUST 抛 ValueError（登记制，不退化开放字符串）。"""
    store = InMemoryStore()
    store.add_node(Node(id="a", name="a", content=""))
    store.add_node(Node(id="b", name="b", content=""))
    with pytest.raises(ValueError, match="unknown edge type"):
        store.add_edge("a", "b", type="因果")  # 未登记


def test_add_edge_self_loop_is_noop():
    """自环 MUST 不建边（返回空串）。"""
    store = InMemoryStore()
    store.add_node(Node(id="a", name="a", content=""))
    assert store.add_edge("a", "a", type=EDGE_ASSOC) == ""
    assert store.get_all_edges() == []


def test_add_edge_missing_endpoint_is_noop():
    """端点不存在 MUST 不建边（返回空串，防悬空边）。"""
    store = InMemoryStore()
    store.add_node(Node(id="a", name="a", content=""))
    assert store.add_edge("a", "ghost", type=EDGE_ASSOC) == ""
    assert store.get_all_edges() == []


def test_add_edge_returns_existing_on_dedup_assoc():
    """同一 (source, target, 关联) 去重：返回既有 id（一条只存一份）。"""
    store = InMemoryStore()
    store.add_node(Node(id="a", name="a", content=""))
    store.add_node(Node(id="b", name="b", content=""))
    eid1 = store.add_edge("a", "b", type=EDGE_ASSOC)
    eid2 = store.add_edge("a", "b", type=EDGE_ASSOC)
    assert eid1 == eid2
    assert len(store.get_all_edges()) == 1


def test_add_edge_mutex_dedup_unordered():
    """互斥按无序对 {s,t} 去重：A→B 与 B→A 视为同一条。"""
    store = InMemoryStore()
    store.add_node(Node(id="a", name="a", content=""))
    store.add_node(Node(id="b", name="b", content=""))
    eid1 = store.add_edge("a", "b", type=EDGE_MUTEX)
    eid2 = store.add_edge("b", "a", type=EDGE_MUTEX)
    assert eid1 == eid2
    assert len([e for e in store.get_all_edges() if e.type == EDGE_MUTEX]) == 1


# ── get_relations 载重规则（核心不反查事件）（#22 核心契约）────────────────


def _store_with(nodes: list[Node], edges: list[tuple[str, str, str]]):
    store = InMemoryStore()
    for n in nodes:
        store.add_node(n)
    for s, t, typ in edges:
        store.add_edge(s, t, type=typ)
    return store


def test_get_relations_returns_both_endpoints():
    """get_relations 返回该节点作任一端的边（反查，双向可达）。"""
    store = _store_with(
        [Node(id="a", name="a", content=""), Node(id="b", name="b", content=""),
         Node(id="c", name="c", content="")],
        [("a", "b", EDGE_ASSOC), ("c", "a", EDGE_ASSOC)],
    )
    rels = {e.source_id + ">" + e.target_id for e in store.get_relations("a")}
    assert rels == {"a>b", "c>a"}


def test_get_relations_core_node_filters_event_edge():
    """载重规则：核心节点（概念/事实）get_relations MUST 不含对端为事件的关联边。"""
    store = _store_with(
        [Node(id="user", name="用户", content="", node_class=CLASS_CONCEPT),
         Node(id="evt", name="事件", content="", node_class=CLASS_EVENT)],
        [("evt", "user", EDGE_ASSOC)],  # 事件 → 用户（背书）
    )
    # 核心侧（用户）不反查事件
    assert store.get_relations("user") == []
    # 事件侧仍可达核心
    assert len(store.get_relations("evt")) == 1


def test_get_relations_event_node_still_reaches_core():
    """事件侧 get_relations 仍返回指向核心的关联边（事件可达核心，单向载重）。"""
    store = _store_with(
        [Node(id="c", name="c", content="", node_class=CLASS_CONCEPT),
         Node(id="f", name="f", content="", node_class=CLASS_FACT),
         Node(id="e", name="e", content="", node_class=CLASS_EVENT)],
        [("e", "c", EDGE_ASSOC), ("e", "f", EDGE_ASSOC)],
    )
    assert len(store.get_relations("e")) == 2


def test_get_relations_fact_node_keeps_mutex():
    """互斥（事实↔事实）不受载重过滤：事实节点 get_relations 含互斥边。"""
    store = _store_with(
        [Node(id="fa", name="fa", content="", node_class=CLASS_FACT),
         Node(id="fb", name="fb", content="", node_class=CLASS_FACT)],
        [("fa", "fb", EDGE_MUTEX)],
    )
    assert len(store.get_relations("fa")) == 1
    assert store.get_relations("fa")[0].type == EDGE_MUTEX


# ── get_out_hierarchy（下钻成员 = 关联出边目标）（#22）────────────────────


def test_get_out_hierarchy_returns_assoc_out_targets():
    """get_out_hierarchy 返回该节点作 source 的关联出边目标（组织层级下钻）。"""
    store = _store_with(
        [Node(id="hub", name="hub", content="", extensions={"hub": True}),
         Node(id="m1", name="m1", content=""),
         Node(id="m2", name="m2", content="")],
        [("hub", "m1", EDGE_ASSOC), ("hub", "m2", EDGE_ASSOC)],
    )
    children = {n.id for n in store.get_out_hierarchy("hub")}
    assert children == {"m1", "m2"}


# ── SQLite 持久化 round-trip（新 schema：type / node_class / hub）（#22）────


def _sqlite_store(tmp_path):
    store = SQLiteStore({"path": str(tmp_path / "t.db")})
    store.initialize()
    return store


def test_sqlite_roundtrip_preserves_node_class_and_hub(tmp_path):
    """SQLite 存取保真：node_class / hub / type 逐条一致。"""
    store = _sqlite_store(tmp_path)
    store.add_node(Node(id="c", name="概念", content="x", node_class=CLASS_CONCEPT))
    store.add_node(Node(id="h", name="hub", content="y", node_class=CLASS_CONCEPT, extensions={"hub": True}))
    store.add_node(Node(id="e", name="事件", content="z", node_class=CLASS_EVENT))
    store.add_edge("h", "c", type=EDGE_ASSOC)
    store.save()
    store.shutdown()

    store2 = SQLiteStore({"path": str(tmp_path / "t.db")})
    store2.initialize()
    store2.load()
    assert store2.get_node("c").node_class == CLASS_CONCEPT
    assert store2.get_node("h").hub is True
    assert store2.get_node("e").node_class == CLASS_EVENT
    edges = store2.get_all_edges()
    assert len(edges) == 1 and edges[0].type == EDGE_ASSOC


def test_sqlite_schema_has_type_column_no_kind_label(tmp_path):
    """新 schema：edges 表有 type 列、无 kind/label 列。"""
    store = _sqlite_store(tmp_path)
    cols = {row[1] for row in store.conn.execute("PRAGMA table_info(edges)")}
    assert "type" in cols
    assert "kind" not in cols
    assert "label" not in cols
    node_cols = {row[1] for row in store.conn.execute("PRAGMA table_info(nodes)")}
    assert "node_class" in node_cols
    # hub 不再是独立列：它是 extensions["hub"]（随 extensions_json 持久化）
    assert "hub" not in node_cols
    assert "role" not in node_cols


def test_sqlite_no_relation_model_hard_reject(tmp_path):
    """统一模型已删 relation_model 硬拒：同名库重复 initialize 不抛 StoreProvenanceError。"""
    store = _sqlite_store(tmp_path)
    store.shutdown()
    # 重新打开同一库（出处已有 schema_version）→ 不应抛异常
    store2 = SQLiteStore({"path": str(tmp_path / "t.db")})
    store2.initialize()  # 不抛
    store2.shutdown()

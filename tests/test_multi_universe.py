"""multi-universe-graph 边界测试 —— universe 隔离核心不变量（纯 store 层，不经 LLM）。

覆盖：载重双类过滤（同 univ 事件单向 / 跨 univ 双向）、root 单侧过滤（P8）、
get_subgraph BFS 不跨 universe、get_related_events 跨 univ 背书亦返、跨查原语、
Node 默认 / SQLite round-trip / 旧库迁移、概念桥存储语义（去重 + 双向过滤）。

ingest 链路（universe 判定 / event 固定现实 / 元节点 / 归一 / 合并互斥前置判）
见 ``test_multi_universe_ingest.py``（经 mock LLM + WritePipeline）。
"""

from __future__ import annotations

import sqlite3

from mcs.core.token_budget import TokenBudget
from mcs.entities.graph import (
    CLASS_CONCEPT,
    CLASS_EVENT,
    CLASS_FACT,
    EDGE_ASSOC,
    REALITY_UNIVERSE,
    Node,
    SEED_ROOT_ID,
)
from mcs.stores.in_memory import InMemoryStore
from mcs.stores.sqlite_store import SQLiteStore


def _node(
    node_id: str,
    name: str = "x",
    content: str = "",
    node_class: str = CLASS_CONCEPT,
    universe: str = REALITY_UNIVERSE,
) -> Node:
    return Node(
        id=node_id, name=name, content=content, node_class=node_class, universe=universe
    )


def _add(store, node_id: str, **kw) -> Node:
    n = _node(node_id, **kw)
    store.add_node(n)
    return n


def _pair(rels, id_a: str, id_b: str) -> list:
    """rels 中两端为 {id_a, id_b} 的边。"""
    return [e for e in rels if {e.source_id, e.target_id} == {id_a, id_b}]


# === 5.11 Node 默认 universe + SQLite round-trip ===


def test_node_default_universe_is_reality() -> None:
    assert Node(id="a", name="a", content="a").universe == REALITY_UNIVERSE


def test_sqlite_universe_roundtrip(tmp_path) -> None:
    db = str(tmp_path / "g.db")
    s1 = SQLiteStore({"path": db})
    s1.initialize()
    _add(s1, "roman", name="曹操", content="演义", universe="三国演义")
    _add(s1, "real", name="曹操", content="正史", universe=REALITY_UNIVERSE)
    s1.save_full()
    s1.shutdown()

    s2 = SQLiteStore({"path": db})
    s2.initialize()
    s2.load()
    assert s2.get_node("roman").universe == "三国演义"
    assert s2.get_node("real").universe == REALITY_UNIVERSE


# === 5.10 旧库迁移（无 universe 列 → 补列 + 全 __reality__） ===


def test_old_db_migration_fills_reality(tmp_path) -> None:
    db = str(tmp_path / "old.db")
    conn = sqlite3.connect(db)
    conn.execute(
        "CREATE TABLE nodes (id TEXT PRIMARY KEY, name TEXT, content TEXT, "
        "node_class TEXT, extensions_json TEXT)"
    )
    conn.execute(
        "CREATE TABLE edges (id TEXT PRIMARY KEY, source_id TEXT, target_id TEXT, "
        "type TEXT, priority REAL, extensions_json TEXT)"
    )
    conn.execute("CREATE TABLE meta (key TEXT PRIMARY KEY, value TEXT)")
    conn.execute(
        "INSERT INTO nodes (id, name, content, node_class, extensions_json) "
        "VALUES ('n1','a','a','概念','{}')"
    )
    conn.commit()
    conn.close()

    s = SQLiteStore({"path": db})
    s.initialize()  # 补列
    s.load()
    assert s.get_node("n1").universe == REALITY_UNIVERSE
    cols = {row[1] for row in s.conn.execute("PRAGMA table_info(nodes)")}
    assert "universe" in cols


# === 5.6 载重双类过滤 ===


def test_cross_universe_edge_bidirectionally_filtered() -> None:
    """跨 universe 边：两端 get_relations 都不返（双向过滤）。"""
    s = InMemoryStore()
    _add(s, "a", universe="三国演义")
    _add(s, "b", universe=REALITY_UNIVERSE)
    s.add_edge("a", "b", type=EDGE_ASSOC)
    assert not _pair(s.get_relations("a"), "a", "b")
    assert not _pair(s.get_relations("b"), "a", "b")


def test_same_universe_event_edge_unidirectional() -> None:
    """同 universe 事件边：核心节点侧过滤、事件侧可达（单向）。"""
    s = InMemoryStore()
    _add(s, "c", universe=REALITY_UNIVERSE)
    _add(s, "e", node_class=CLASS_EVENT, universe=REALITY_UNIVERSE)
    s.add_edge("e", "c", type=EDGE_ASSOC)
    assert not _pair(s.get_relations("c"), "c", "e")  # 核心侧过滤
    assert _pair(s.get_relations("e"), "c", "e")  # 事件侧可达


def test_cross_universe_edges_primitive_reachable() -> None:
    """跨 universe 桥经 get_cross_universe_edges 两端均可取回（绕载重）。"""
    s = InMemoryStore()
    _add(s, "a", universe="U1")
    _add(s, "b", universe="U2")
    s.add_edge("a", "b", type=EDGE_ASSOC)
    assert len(s.get_cross_universe_edges("a")) == 1
    assert len(s.get_cross_universe_edges("b")) == 1


# === 5.7 event 跨 univ 背书双向过滤 + 5.19 get_related_events 跨 univ 亦返 ===


def test_event_cross_universe_endorsement_filtered_but_related_events_returned() -> None:
    """现实摄入 event(__reality__) → 作品 fact(work)：两端 get_relations 双向过滤，
    get_related_events 仍返（绕载重，要出处）。"""
    s = InMemoryStore()
    _add(s, "f", node_class=CLASS_FACT, universe="三国演义")
    _add(s, "e", node_class=CLASS_EVENT, universe=REALITY_UNIVERSE)
    s.add_edge("e", "f", type=EDGE_ASSOC)
    assert not _pair(s.get_relations("f"), "e", "f")
    assert not _pair(s.get_relations("e"), "e", "f")
    events = s.get_related_events("f")
    assert any(ev.id == "e" for ev in events)  # 跨 univ 亦返


# === 5.9 root 单侧过滤（P8 阻塞级修复） ===


def test_root_out_hierarchy_single_side_filter() -> None:
    """root（自身 __reality__）下挂现实孤儿 + 作品孤儿：
    universe=U 取 target.universe==U（即使 root→孤儿边跨 universe）。"""
    s = InMemoryStore()
    _add(s, SEED_ROOT_ID, universe=REALITY_UNIVERSE)
    _add(s, "r", universe=REALITY_UNIVERSE)
    _add(s, "w", universe="三国演义")
    s.add_edge(SEED_ROOT_ID, "r", type=EDGE_ASSOC)
    s.add_edge(SEED_ROOT_ID, "w", type=EDGE_ASSOC)
    assert {n.id for n in s.get_out_hierarchy(SEED_ROOT_ID, universe="三国演义")} == {"w"}
    assert {n.id for n in s.get_out_hierarchy(SEED_ROOT_ID, universe=REALITY_UNIVERSE)} == {
        "r"
    }
    # 无参 → 全部（旧库兼容）
    assert {n.id for n in s.get_out_hierarchy(SEED_ROOT_ID)} == {"r", "w"}


def test_normal_node_out_hierarchy_equivalent_to_two_end_same_universe() -> None:
    """普通节点 A 传 universe=A.universe 等价两端同 universe。"""
    s = InMemoryStore()
    _add(s, "a", universe="U1")
    _add(s, "s", universe="U1")
    _add(s, "d", universe="U2")
    s.add_edge("a", "s", type=EDGE_ASSOC)
    s.add_edge("a", "d", type=EDGE_ASSOC)
    assert {n.id for n in s.get_out_hierarchy("a", universe="U1")} == {"s"}


# === 5.18 get_subgraph BFS 不跨 universe ===


def test_subgraph_bfs_does_not_cross_universe() -> None:
    """A(univ=X) 经概念桥连 C(univ=Y)：get_subgraph(A) 活跃子图只含 X 节点。"""
    s = InMemoryStore()
    _add(s, "a", universe="X")
    _add(s, "b", universe="X")
    _add(s, "c", universe="Y")
    s.add_edge("a", "b", type=EDGE_ASSOC)
    s.add_edge("a", "c", type=EDGE_ASSOC)  # 跨 univ 桥
    tb = TokenBudget(max_tokens=10000)
    sub = s.get_subgraph("a", tb)
    assert {n.id for n in sub.nodes} == {"a", "b"}


# === 5.15 概念桥存储语义（建后双向过滤 / get_cross_universe_edges 可达 / 同对去重） ===


def test_concept_bridge_storage_semantics() -> None:
    s = InMemoryStore()
    _add(s, "roman_caocao", universe="三国演义")
    _add(s, "real_caocao", universe=REALITY_UNIVERSE)
    s.add_edge("roman_caocao", "real_caocao", type=EDGE_ASSOC)
    # get_relations 双向过滤（不进活跃视图）
    assert not _pair(s.get_relations("roman_caocao"), "roman_caocao", "real_caocao")
    assert not _pair(s.get_relations("real_caocao"), "roman_caocao", "real_caocao")
    # get_cross_universe_edges 可达
    assert len(s.get_cross_universe_edges("roman_caocao")) == 1
    # 同对去重：再建同边不产第二条
    s.add_edge("roman_caocao", "real_caocao", type=EDGE_ASSOC)
    assert len(s.get_cross_universe_edges("roman_caocao")) == 1


# === 5.8 fanout 限同 universe（root 按 universe 分组，P8 结构性护栏） ===


def test_fanout_root_groups_split_by_universe() -> None:
    """fanout 对 root 按 universe 分组：不同 universe 孤儿不混同 decide_hub 邻域
    （保铁律一：估算 == 渲染，邻域不混 universe）。"""
    from mcs.plugins.maintenance.fanout_reducer import FanoutReducerPlugin

    s = InMemoryStore()
    _add(s, SEED_ROOT_ID, universe=REALITY_UNIVERSE)
    _add(s, "r1", universe=REALITY_UNIVERSE)
    _add(s, "r2", universe=REALITY_UNIVERSE)
    _add(s, "w1", universe="三国演义")
    s.add_edge(SEED_ROOT_ID, "r1", type=EDGE_ASSOC)
    s.add_edge(SEED_ROOT_ID, "r2", type=EDGE_ASSOC)
    s.add_edge(SEED_ROOT_ID, "w1", type=EDGE_ASSOC)
    plugin = FanoutReducerPlugin()
    root = s.get_node(SEED_ROOT_ID)
    groups = {u: {n.id for n in kids} for u, kids in plugin._iter_node_groups(root, s)}
    assert groups.get(REALITY_UNIVERSE) == {"r1", "r2"}
    assert groups.get("三国演义") == {"w1"}

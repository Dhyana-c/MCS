"""边扩展模型测试（edge-extension-model capability）。

覆盖 tasks 8.1–8.7：边扩展存取 / 反查 / SQLite 编解码保真、字段级渲染可见性
（render→None 隐藏 / 按 purpose 切换）、边渲染 == 估算（查询侧一致性）、
派生 scorer 默认 0.0、重组 / 快照保真（独立 dict）、provenance 三态校验、
旧库补列后可写。task 8.8（基线全量回归）由全仓 pytest 兜底。
"""

from __future__ import annotations

import json
import logging
import sqlite3

import pytest

from mcs.core.context_renderer import ContextRenderer
from mcs.core.plugin import PluginType
from mcs.core.plugin_manager import PluginManager
from mcs.core.token_budget import TokenBudget
from mcs.entities.graph import Edge, Node
from mcs.interfaces.edge_extension import EdgeExtensionInterface
from mcs.interfaces.priority_scorer import DefaultPriorityScorer, PriorityScorer
from mcs.plugins.maintenance.fanout_reducer import FanoutReducerPlugin
from mcs.stores.in_memory import InMemoryStore
from mcs.stores.sqlite_store import SCHEMA_VERSION, SQLiteStore, StoreProvenanceError


# ─── 测试用边扩展插件 ──────────────────────────────────────────────────────────


class ActivityEdgeExt(EdgeExtensionInterface):
    """``edge.extensions["activity"] = {"count": int}``；仅 select_facts 渲染活跃数。"""

    def get_name(self) -> str:
        return "activity"

    def get_type(self) -> PluginType:
        return PluginType.EDGE_EXTENSION

    def schema(self) -> dict:
        return {"count": "int"}

    def default(self) -> dict:
        return {"count": 0}

    def serialize(self, data):
        d = data or {}
        return {"count": d.get("count", 0)}

    def deserialize(self, data):
        d = data or {}
        return {"count": d.get("count", 0)}

    def render(self, edge: Edge, purpose: str) -> str | None:
        if purpose != "select_facts":
            return None
        d = (edge.extensions or {}).get("activity", {})
        c = d.get("count", 0) if isinstance(d, dict) else 0
        return f"活跃={c}" if c else None


class HiddenMetaEdgeExt(EdgeExtensionInterface):
    """后台元数据扩展：所有 purpose 都返回 None（隐藏、永不渲染）。"""

    def get_name(self) -> str:
        return "hidden_meta"

    def get_type(self) -> PluginType:
        return PluginType.EDGE_EXTENSION

    def schema(self) -> dict:
        return {"v": "int"}

    def default(self) -> dict:
        return {"v": 0}

    def serialize(self, data):
        return dict(data or {"v": 0})

    def deserialize(self, data):
        return dict(data or {"v": 0})

    def render(self, edge: Edge, purpose: str) -> str | None:
        return None


# ─── 8.1 边扩展存取 / 反查 / 编解码保真 ─────────────────────────────────────────


def test_edge_default_extensions_is_independent_empty_dict():
    e = Edge(source_id="a", target_id="b")
    assert e.extensions == {}
    e2 = Edge(source_id="a", target_id="b")
    e.extensions["x"] = 1
    assert e2.extensions == {}  # 各实例不共享（default_factory）


def test_inmemory_add_edge_carries_extensions_and_reverse_lookup():
    store = InMemoryStore()
    store.add_node(Node(id="a", name="A", content=""))
    store.add_node(Node(id="b", name="B", content=""))
    store.add_edge(
        "a", "b", kind="fact", label="likes",
        extensions={"activity": {"count": 3}},
    )
    from_a = store.get_facts("a")
    from_b = store.get_facts("b")
    assert len(from_a) == 1 and len(from_b) == 1
    # 两端反查返回的同一对象都带完整 extensions
    assert from_a[0].extensions.get("activity", {}).get("count") == 3
    assert from_b[0].id == from_a[0].id
    assert from_b[0].extensions.get("activity", {}).get("count") == 3


def test_sqlite_extensions_json_roundtrip_preserves_fidelity(tmp_path):
    db = str(tmp_path / "ext.db")
    ext = ActivityEdgeExt()
    store = SQLiteStore({"path": db})
    store.initialize(
        relation_model="property_graph",
        edge_extensions={"activity": ext},
    )
    store.add_node(Node(id="a", name="A", content=""))
    store.add_node(Node(id="b", name="B", content=""))
    store.add_edge(
        "a", "b", kind="fact", label="likes",
        extensions={"activity": {"count": 7}},
    )
    store.save_full()
    store.shutdown()

    store2 = SQLiteStore({"path": db})
    store2.initialize(
        relation_model="property_graph",
        edge_extensions={"activity": ActivityEdgeExt()},
    )
    store2.load()
    facts = store2.get_facts("a")
    assert len(facts) == 1
    assert facts[0].extensions.get("activity", {}).get("count") == 7
    # 反查另一端同样完整
    assert store2.get_facts("b")[0].extensions.get("activity", {}).get("count") == 7


def test_sqlite_extensions_json_column_stored_as_dict(tmp_path):
    """落盘的 extensions_json 是经 serialize 的 dict（非 repr 字符串）。"""
    db = str(tmp_path / "raw.db")
    ext = ActivityEdgeExt()
    store = SQLiteStore({"path": db})
    store.initialize(relation_model="property_graph", edge_extensions={"activity": ext})
    store.add_node(Node(id="a", name="A", content=""))
    store.add_node(Node(id="b", name="B", content=""))
    store.add_edge("a", "b", kind="fact", label="x", extensions={"activity": {"count": 2}})
    store.save()
    raw = store.conn.execute(
        "SELECT extensions_json FROM edges WHERE source_id='a'"
    ).fetchone()[0]
    parsed = json.loads(raw)
    assert parsed == {"activity": {"count": 2}}


# ─── 8.2 字段级渲染可见性 ────────────────────────────────────────────────────────


def test_render_fact_edge_no_extensions_is_baseline():
    edge = Edge(source_id="a", target_id="b", kind="fact", label="likes")
    nm = {"a": Node(id="a", name="A", content=""), "b": Node(id="b", name="B", content="")}
    assert ContextRenderer.render_fact_edge(edge, nm) == "A —likes→ B"


def test_render_hidden_extension_adds_no_fragment():
    edge = Edge(
        source_id="a", target_id="b", kind="fact", label="likes",
        extensions={"hidden_meta": {"v": 9}},
    )
    nm = {"a": Node(id="a", name="A", content=""), "b": Node(id="b", name="B", content="")}
    out = ContextRenderer.render_fact_edge(
        edge, nm, extensions=[HiddenMetaEdgeExt()], purpose="select_facts"
    )
    assert out == "A —likes→ B"  # 隐藏字段零渲染


def test_render_visible_extension_appends_fragment_at_select_facts():
    edge = Edge(
        source_id="a", target_id="b", kind="fact", label="likes",
        extensions={"activity": {"count": 4}},
    )
    nm = {"a": Node(id="a", name="A", content=""), "b": Node(id="b", name="B", content="")}
    out = ContextRenderer.render_fact_edge(
        edge, nm, extensions=[ActivityEdgeExt()], purpose="select_facts"
    )
    assert "A —likes→ B" in out
    assert "活跃=4" in out


def test_visibility_differs_by_purpose():
    """同一边：select_facts 可见、decide_hub 隐藏。"""
    edge = Edge(
        source_id="a", target_id="b", kind="fact", label="likes",
        extensions={"activity": {"count": 4}},
    )
    nm = {"a": Node(id="a", name="A", content=""), "b": Node(id="b", name="B", content="")}
    exts = [ActivityEdgeExt()]
    visible = ContextRenderer.render_fact_edge(edge, nm, exts, "select_facts")
    hidden = ContextRenderer.render_fact_edge(edge, nm, exts, "decide_hub")
    assert "活跃=4" in visible
    assert "活跃=4" not in hidden


def test_render_facts_passes_purpose_and_edge_extensions():
    pm = PluginManager()
    pm.register(ActivityEdgeExt())
    renderer = ContextRenderer(pm)
    nodes = [Node(id="a", name="A", content=""), Node(id="b", name="B", content="")]
    edges = [Edge(
        source_id="a", target_id="b", kind="fact", label="likes",
        extensions={"activity": {"count": 5}},
    )]
    out = renderer.render_facts(nodes, edges, purpose="select_facts", mode="property_graph")
    assert "活跃=5" in out  # 边扩展片段经 render_facts 透传进来


# ─── 8.3 边渲染 == 估算（查询侧一致性）+ 守门回归 ────────────────────────────────


def test_estimate_fact_edge_equals_render_with_visible_extension():
    tb = TokenBudget(8000)
    edge = Edge(
        source_id="a", target_id="b", kind="fact", label="likes",
        extensions={"activity": {"count": 6}},
    )
    nm = {"a": Node(id="a", name="A", content=""), "b": Node(id="b", name="B", content="")}
    exts = [ActivityEdgeExt()]
    rendered = ContextRenderer.render_fact_edge(edge, nm, exts, "select_facts")
    assert tb.estimate_fact_edge(edge, nm, exts, "select_facts") == tb.estimate(rendered)


def test_estimate_assoc_edge_equals_render():
    tb = TokenBudget(8000)
    edge = Edge(
        source_id="a", target_id="b", kind="assoc",
        extensions={"activity": {"count": 2}},
    )
    nm = {"a": Node(id="a", name="A", content=""), "b": Node(id="b", name="B", content="")}
    exts = [ActivityEdgeExt()]
    rendered = ContextRenderer.render_assoc_edge(edge, nm, exts, "select_facts")
    assert tb.estimate_assoc_edge(edge, nm, exts, "select_facts") == tb.estimate(rendered)


def test_estimate_hidden_extension_not_counted():
    tb = TokenBudget(8000)
    edge = Edge(
        source_id="a", target_id="b", kind="fact", label="likes",
        extensions={"hidden_meta": {"v": 1}},
    )
    nm = {"a": Node(id="a", name="A", content=""), "b": Node(id="b", name="B", content="")}
    # 隐藏字段不计入：带扩展与不带扩展估算相等
    without = tb.estimate_fact_edge(edge, nm, None, "select_facts")
    with_hidden = tb.estimate_fact_edge(edge, nm, [HiddenMetaEdgeExt()], "select_facts")
    assert without == with_hidden


def test_estimate_node_gatekeeping_unchanged_regression():
    """守门 estimate_node：purpose=decide_hub、extensions=None，行为不变。"""
    tb = TokenBudget(8000)
    node = Node(id="a", name="A", content="一段足够长的内容" * 10)
    expected = tb.estimate(
        ContextRenderer.render_node_full(node, "decide_hub", is_focus=True, extensions=None)
    )
    assert tb.estimate_node(node) == expected


# ─── 8.4 派生 scorer 默认 0.0 ───────────────────────────────────────────────────


def test_default_priority_scorer_returns_zero():
    scorer = DefaultPriorityScorer()
    edge = Edge(source_id="a", target_id="b", extensions={"activity": {"count": 99}})
    assert scorer.score(edge) == 0.0


def test_priority_scorer_is_abstract():
    with pytest.raises(TypeError):
        PriorityScorer()  # type: ignore[abstract]


def test_written_edge_priority_still_zero():
    store = InMemoryStore()
    store.add_node(Node(id="a", name="A", content=""))
    store.add_node(Node(id="b", name="B", content=""))
    store.add_edge("a", "b", kind="fact", label="x", extensions={"activity": {"count": 1}})
    assert store.get_facts("a")[0].priority == 0.0  # 零行为变化


def test_store_holds_priority_scorer_seam():
    """store 持有 scorer（seam），Phase 1 不在 chokepoint 调用。"""
    mem = InMemoryStore()
    assert isinstance(mem._priority_scorer, PriorityScorer)
    sq = SQLiteStore({"path": ":memory:"})
    sq.initialize()
    assert isinstance(sq._priority_scorer, PriorityScorer)
    assert sq._priority_scorer.score(Edge("a", "b")) == 0.0


# ─── 8.5 重组保真 / 快照独立 dict ───────────────────────────────────────────────


def test_migrate_edges_preserves_extensions():
    store = InMemoryStore()
    for nid in ("a", "b", "c"):
        store.add_node(Node(id=nid, name=nid, content=""))
    store.add_edge(
        "a", "b", kind="fact", label="likes",
        extensions={"activity": {"count": 8}},
    )
    plugin = FanoutReducerPlugin()
    plugin._migrate_edges("a", "c", store)  # a→b 迁移为 c→b
    migrated = store.get_edges_between("c", "b")
    assert len(migrated) == 1
    assert migrated[0].extensions.get("activity", {}).get("count") == 8  # 保真未丢


def test_snapshot_edge_extensions_is_independent_dict():
    for store in (InMemoryStore(), SQLiteStore({"path": ":memory:"})):
        if isinstance(store, SQLiteStore):
            store.initialize()
        store.add_node(Node(id="a", name="A", content=""))
        store.add_node(Node(id="b", name="B", content=""))
        store.add_edge("a", "b", kind="fact", label="x", extensions={"activity": {"count": 3}})
        eid = next(iter(store._edges))
        live = store._edges[eid]
        snap = store.snapshot()
        snap_edge = snap["edges"][eid]
        # 快照深拷：独立 dict（防 restore 后引用共享、改动串味）
        assert snap_edge.extensions is not live.extensions
        assert snap_edge.extensions == live.extensions


def test_snapshot_restore_roundtrip_preserves_edge_extensions(tmp_path):
    for store in (
        InMemoryStore(),
        SQLiteStore({"path": str(tmp_path / "snap.db")}),
    ):
        if isinstance(store, SQLiteStore):
            store.initialize()
        store.add_node(Node(id="a", name="A", content=""))
        store.add_node(Node(id="b", name="B", content=""))
        fid = store.add_edge("a", "b", kind="fact", label="x", extensions={"activity": {"count": 5}})
        snap = store.snapshot()
        store.delete_edge(fid)
        store.add_edge("a", "b", kind="fact", label="x", extensions={"activity": {"count": 99}})
        store.restore(snap)
        assert store.get_facts("a")[0].extensions.get("activity", {}).get("count") == 5


# ─── 8.6 provenance 三态校验 ────────────────────────────────────────────────────


def test_provenance_relation_model_mismatch_rejected(tmp_path):
    db = str(tmp_path / "rm.db")
    s1 = SQLiteStore({"path": db})
    s1.initialize(relation_model="property_graph")
    s1.shutdown()
    s2 = SQLiteStore({"path": db})
    with pytest.raises(StoreProvenanceError):
        s2.initialize(relation_model="attribute_node")  # 唯一硬拒


def test_provenance_extension_set_change_warns_but_passes(tmp_path, caplog):
    db = str(tmp_path / "extset.db")
    ext = ActivityEdgeExt()
    s1 = SQLiteStore({"path": db})
    s1.initialize(relation_model="property_graph", edge_extensions={"activity": ext})
    s1.shutdown()
    s2 = SQLiteStore({"path": db})
    with caplog.at_level(logging.WARNING):
        # 扩展集变化（新增 extra）：仅告警、放行
        s2.initialize(
            relation_model="property_graph",
            edge_extensions={"activity": ActivityEdgeExt(), "extra": HiddenMetaEdgeExt()},
        )
    assert s2.conn is not None
    assert any("扩展集" in r.message for r in caplog.records)
    # 放行后 meta 已刷新为当前集
    meta_ext = json.loads(s2._read_meta_all().get("extensions", "[]"))
    assert set(meta_ext) == {"activity", "extra"}


def test_provenance_same_config_no_warning(tmp_path, caplog):
    db = str(tmp_path / "same.db")
    ext = ActivityEdgeExt()
    s1 = SQLiteStore({"path": db})
    s1.initialize(relation_model="property_graph", edge_extensions={"activity": ext})
    s1.shutdown()
    s2 = SQLiteStore({"path": db})
    with caplog.at_level(logging.WARNING):
        s2.initialize(relation_model="property_graph", edge_extensions={"activity": ActivityEdgeExt()})
    assert not any("扩展集" in r.message for r in caplog.records)


def test_provenance_missing_meta_backfilled_and_warns_for_legacy(tmp_path, caplog):
    db = str(tmp_path / "nolegacymeta.db")
    s1 = SQLiteStore({"path": db})
    s1.initialize(relation_model="property_graph")
    s1.add_node(Node(id="a", name="A", content=""))  # 有数据 → 真旧库
    s1.save()  # 落盘（含 meta）；node 'a' 进 SQLite
    s1.conn.execute("DELETE FROM meta")  # 抹掉出处模拟缺失
    s1.conn.commit()
    s1.shutdown()
    s2 = SQLiteStore({"path": db})
    with caplog.at_level(logging.WARNING):
        s2.initialize(relation_model="property_graph")
    meta = s2._read_meta_all()
    assert meta.get("relation_model") == "property_graph"  # 补写放行
    assert meta.get("schema_version") == SCHEMA_VERSION
    assert any("旧库" in r.message for r in caplog.records)


# ─── 8.7 旧库补列后可写 ─────────────────────────────────────────────────────────


def test_legacy_db_without_extensions_json_column_backfills_and_writable(tmp_path):
    db = str(tmp_path / "truelegacy.db")
    # 手建一个无 extensions_json 列、无 meta 表的真旧库
    conn = sqlite3.connect(db)
    conn.executescript(
        """
        CREATE TABLE nodes (
            id TEXT PRIMARY KEY, name TEXT, content TEXT, role TEXT, extensions_json TEXT
        );
        CREATE TABLE edges (
            id TEXT PRIMARY KEY, source_id TEXT, target_id TEXT,
            kind TEXT, label TEXT, priority REAL
        );
        INSERT INTO nodes (id, name, content, role) VALUES ('a', 'A', '', 'concept');
        INSERT INTO nodes (id, name, content, role) VALUES ('b', 'B', '', 'concept');
        INSERT INTO edges (id, source_id, target_id, kind, label, priority)
            VALUES ('e1', 'a', 'b', 'fact', 'likes', 0.0);
        """
    )
    conn.commit()
    conn.close()

    # 开库：MUST 补 extensions_json 列 + 写 meta（先于读写）
    store = SQLiteStore({"path": db})
    store.initialize(
        relation_model="property_graph",
        edge_extensions={"activity": ActivityEdgeExt()},
    )
    store.load()  # 把旧库 a/b/e1 载入内存（真实装配在 load-on-startup）
    cols = {r[1] for r in store.conn.execute("PRAGMA table_info(edges)")}
    assert "extensions_json" in cols  # 补列成功
    meta = store._read_meta_all()
    assert meta.get("relation_model") == "property_graph"  # 补 meta

    # 写入含 extensions_json 的 INSERT 不抛 OperationalError
    store.add_edge(
        "b", "a", kind="fact", label="knows",
        extensions={"activity": {"count": 5}},
    )
    store.save()
    store.shutdown()

    store2 = SQLiteStore({"path": db})
    store2.initialize(
        relation_model="property_graph",
        edge_extensions={"activity": ActivityEdgeExt()},
    )
    store2.load()
    e = store2.get_edges_between("b", "a")[0]
    assert e.extensions.get("activity", {}).get("count") == 5
    # 旧边（无 extensions）load 后 extensions 为空字典、不崩
    old = store2.get_edges_between("a", "b")[0]
    assert old.extensions == {}


def test_fresh_db_does_not_repeatedly_alter_extensions_column(tmp_path):
    """新建库已含 extensions_json，补列检测识别已存在、不重复 ALTER、不报错。"""
    db = str(tmp_path / "fresh.db")
    s1 = SQLiteStore({"path": db})
    s1.initialize()
    cols_before = {r[1] for r in s1.conn.execute("PRAGMA table_info(edges)")}
    s1.shutdown()
    s2 = SQLiteStore({"path": db})
    s2.initialize()  # 再次开库不应报错、列仍在
    cols_after = {r[1] for r in s2.conn.execute("PRAGMA table_info(edges)")}
    assert cols_before == cols_after
    assert "extensions_json" in cols_after

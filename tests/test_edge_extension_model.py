"""边扩展模型测试（edge-extension-model capability，统一图模型适配）。

覆盖：边扩展存取 / 反查 / SQLite 编解码保真、字段级渲染可见性
（render→None 隐藏 / 按 purpose 切换）、边渲染 == 估算（查询侧一致性）、
派生 scorer 默认 0.0、重组 / 快照保真（独立 dict）、provenance 扩展集校验。

统一图模型下边仅 ``关联`` / ``互斥``（无 kind/label）；边扩展机制（``Edge.extensions``
+ ``EdgeExtensionInterface``）不变。关系边统一渲染 ``主 — 宾``（type 不计 token）。
"""

from __future__ import annotations

import json
import logging

import pytest

from mcs.core.context_renderer import ContextRenderer
from mcs.core.plugin import PluginType
from mcs.core.plugin_manager import PluginManager
from mcs.core.token_budget import TokenBudget
from mcs.entities.graph import CLASS_FACT, EDGE_ASSOC, EDGE_MUTEX, Edge, Node
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


def _nm():
    return {
        "a": Node(id="a", name="A", content=""),
        "b": Node(id="b", name="B", content=""),
    }


# ─── 边扩展存取 / 反查 / 编解码保真 ─────────────────────────────────────────


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
        "a", "b", type=EDGE_ASSOC,
        extensions={"activity": {"count": 3}},
    )
    from_a = store.get_relations("a")
    from_b = store.get_relations("b")
    assert len(from_a) == 1 and len(from_b) == 1
    # 两端反查返回的同一对象都带完整 extensions
    assert from_a[0].extensions.get("activity", {}).get("count") == 3
    assert from_b[0].id == from_a[0].id
    assert from_b[0].extensions.get("activity", {}).get("count") == 3


def test_sqlite_extensions_json_roundtrip_preserves_fidelity(tmp_path):
    db = str(tmp_path / "ext.db")
    ext = ActivityEdgeExt()
    store = SQLiteStore({"path": db})
    store.initialize(edge_extensions={"activity": ext})
    store.add_node(Node(id="a", name="A", content=""))
    store.add_node(Node(id="b", name="B", content=""))
    store.add_edge(
        "a", "b", type=EDGE_ASSOC,
        extensions={"activity": {"count": 7}},
    )
    store.save_full()
    store.shutdown()

    store2 = SQLiteStore({"path": db})
    store2.initialize(edge_extensions={"activity": ActivityEdgeExt()})
    store2.load()
    facts = store2.get_relations("a")
    assert len(facts) == 1
    assert facts[0].extensions.get("activity", {}).get("count") == 7
    # 反查另一端同样完整
    assert store2.get_relations("b")[0].extensions.get("activity", {}).get("count") == 7


def test_sqlite_extensions_json_column_stored_as_dict(tmp_path):
    """落盘的 extensions_json 是经 serialize 的 dict（非 repr 字符串）。"""
    db = str(tmp_path / "raw.db")
    ext = ActivityEdgeExt()
    store = SQLiteStore({"path": db})
    store.initialize(edge_extensions={"activity": ext})
    store.add_node(Node(id="a", name="A", content=""))
    store.add_node(Node(id="b", name="B", content=""))
    store.add_edge("a", "b", type=EDGE_ASSOC, extensions={"activity": {"count": 2}})
    store.save()
    raw = store.conn.execute(
        "SELECT extensions_json FROM edges WHERE source_id='a'"
    ).fetchone()[0]
    parsed = json.loads(raw)
    assert parsed == {"activity": {"count": 2}}


# ─── 字段级渲染可见性（关系边渲染 主 — 宾，无 label）────────────────────────


def test_render_relation_edge_no_extensions_is_baseline():
    edge = Edge(source_id="a", target_id="b", type=EDGE_ASSOC)
    assert ContextRenderer.render_relation_edge(edge, _nm()) == "A — B"


def test_render_hidden_extension_adds_no_fragment():
    edge = Edge(
        source_id="a", target_id="b", type=EDGE_ASSOC,
        extensions={"hidden_meta": {"v": 9}},
    )
    out = ContextRenderer.render_relation_edge(
        edge, _nm(), extensions=[HiddenMetaEdgeExt()], purpose="select_facts"
    )
    assert out == "A — B"  # 隐藏字段零渲染


def test_render_visible_extension_appends_fragment_at_select_facts():
    edge = Edge(
        source_id="a", target_id="b", type=EDGE_ASSOC,
        extensions={"activity": {"count": 4}},
    )
    out = ContextRenderer.render_relation_edge(
        edge, _nm(), extensions=[ActivityEdgeExt()], purpose="select_facts"
    )
    assert "A — B" in out
    assert "活跃=4" in out


def test_visibility_differs_by_purpose():
    """同一边：select_facts 可见、decide_hub 隐藏。"""
    edge = Edge(
        source_id="a", target_id="b", type=EDGE_ASSOC,
        extensions={"activity": {"count": 4}},
    )
    exts = [ActivityEdgeExt()]
    visible = ContextRenderer.render_relation_edge(edge, _nm(), exts, "select_facts")
    hidden = ContextRenderer.render_relation_edge(edge, _nm(), exts, "decide_hub")
    assert "活跃=4" in visible
    assert "活跃=4" not in hidden


def test_render_facts_passes_purpose_and_edge_extensions():
    pm = PluginManager()
    pm.register(ActivityEdgeExt())
    renderer = ContextRenderer(pm)
    nodes = [Node(id="a", name="A", content=""), Node(id="b", name="B", content="")]
    edges = [Edge(
        source_id="a", target_id="b", type=EDGE_ASSOC,
        extensions={"activity": {"count": 5}},
    )]
    out = renderer.render_facts(nodes, edges, purpose="select_facts")
    assert "活跃=5" in out  # 边扩展片段经 render_facts 透传进来


# ─── 边渲染 == 估算（查询侧一致性）+ 守门回归 ────────────────────────────────


def test_estimate_relation_edge_equals_render_with_visible_extension():
    tb = TokenBudget(8000)
    edge = Edge(
        source_id="a", target_id="b", type=EDGE_ASSOC,
        extensions={"activity": {"count": 6}},
    )
    exts = [ActivityEdgeExt()]
    rendered = ContextRenderer.render_relation_edge(edge, _nm(), exts, "select_facts")
    assert tb.estimate_relation_edge(edge, _nm(), exts, "select_facts") == tb.estimate(rendered)


def test_estimate_relation_edge_equals_render_assoc():
    tb = TokenBudget(8000)
    edge = Edge(
        source_id="a", target_id="b", type=EDGE_ASSOC,
        extensions={"activity": {"count": 2}},
    )
    exts = [ActivityEdgeExt()]
    rendered = ContextRenderer.render_relation_edge(edge, _nm(), exts, "select_facts")
    assert tb.estimate_relation_edge(edge, _nm(), exts, "select_facts") == tb.estimate(rendered)


def test_estimate_hidden_extension_not_counted():
    tb = TokenBudget(8000)
    edge = Edge(
        source_id="a", target_id="b", type=EDGE_ASSOC,
        extensions={"hidden_meta": {"v": 1}},
    )
    # 隐藏字段不计入：带扩展与不带扩展估算相等
    without = tb.estimate_relation_edge(edge, _nm(), None, "select_facts")
    with_hidden = tb.estimate_relation_edge(edge, _nm(), [HiddenMetaEdgeExt()], "select_facts")
    assert without == with_hidden


def test_estimate_node_gatekeeping_unchanged_regression():
    """守门 estimate_node：purpose=decide_hub、extensions=None，行为不变。"""
    tb = TokenBudget(8000)
    node = Node(id="a", name="A", content="一段足够长的内容" * 10)
    expected = tb.estimate(
        ContextRenderer.render_node_full(node, "decide_hub", is_focus=True, extensions=None)
    )
    assert tb.estimate_node(node) == expected


# ─── 派生 scorer 默认 0.0 ───────────────────────────────────────────────────


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
    store.add_edge("a", "b", type=EDGE_ASSOC, extensions={"activity": {"count": 1}})
    assert store.get_relations("a")[0].priority == 0.0  # 零行为变化


def test_store_holds_priority_scorer_seam():
    """store 持有 scorer（seam），Phase 1 不在 chokepoint 调用。"""
    mem = InMemoryStore()
    assert isinstance(mem._priority_scorer, PriorityScorer)
    sq = SQLiteStore({"path": ":memory:"})
    sq.initialize()
    assert isinstance(sq._priority_scorer, PriorityScorer)
    assert sq._priority_scorer.score(Edge("a", "b")) == 0.0


# ─── 重组保真 / 快照独立 dict ───────────────────────────────────────────────


def test_migrate_edges_preserves_extensions():
    store = InMemoryStore()
    for nid in ("a", "b", "c"):
        store.add_node(Node(id=nid, name=nid, content=""))
    store.add_edge(
        "a", "b", type=EDGE_ASSOC,
        extensions={"activity": {"count": 8}},
    )
    plugin = FanoutReducerPlugin()
    plugin._migrate_edges("a", "c", store)  # a→b 迁移为 c→b
    migrated = store.get_edges_between("c", "b")
    assert len(migrated) == 1
    assert migrated[0].extensions.get("activity", {}).get("count") == 8  # 保真未丢


def test_snapshot_edge_extensions_is_independent_dict(tmp_path):
    for store in (InMemoryStore(), SQLiteStore({"path": str(tmp_path / "snap.db")})):
        if isinstance(store, SQLiteStore):
            store.initialize()
        store.add_node(Node(id="a", name="A", content=""))
        store.add_node(Node(id="b", name="B", content=""))
        store.add_edge("a", "b", type=EDGE_ASSOC, extensions={"activity": {"count": 3}})
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
        SQLiteStore({"path": str(tmp_path / "snap2.db")}),
    ):
        if isinstance(store, SQLiteStore):
            store.initialize()
        store.add_node(Node(id="a", name="A", content=""))
        store.add_node(Node(id="b", name="B", content=""))
        fid = store.add_edge("a", "b", type=EDGE_ASSOC, extensions={"activity": {"count": 5}})
        snap = store.snapshot()
        store.delete_edge(fid)
        store.add_edge("a", "b", type=EDGE_ASSOC, extensions={"activity": {"count": 99}})
        store.restore(snap)
        assert store.get_relations("a")[0].extensions.get("activity", {}).get("count") == 5


# ─── provenance 校验（统一模型：无 relation_model 硬拒；扩展集变化告警放行）──


def test_provenance_no_hard_reject_on_reopen(tmp_path):
    """统一模型已删 relation_model 硬拒：同名库重新 initialize 不抛 StoreProvenanceError。"""
    db = str(tmp_path / "rm.db")
    s1 = SQLiteStore({"path": db})
    s1.initialize()
    s1.shutdown()
    s2 = SQLiteStore({"path": db})
    s2.initialize()  # 不抛
    s2.shutdown()
    # StoreProvenanceError 类型仍可导入、当前不再抛
    assert issubclass(StoreProvenanceError, RuntimeError)


def test_provenance_extension_set_change_warns_but_passes(tmp_path, caplog):
    db = str(tmp_path / "extset.db")
    ext = ActivityEdgeExt()
    s1 = SQLiteStore({"path": db})
    s1.initialize(edge_extensions={"activity": ext})
    s1.shutdown()
    s2 = SQLiteStore({"path": db})
    with caplog.at_level(logging.WARNING):
        # 扩展集变化（新增 extra）：仅告警、放行
        s2.initialize(
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
    s1.initialize(edge_extensions={"activity": ext})
    s1.shutdown()
    s2 = SQLiteStore({"path": db})
    with caplog.at_level(logging.WARNING):
        s2.initialize(edge_extensions={"activity": ActivityEdgeExt()})
    assert not any("扩展集" in r.message for r in caplog.records)


def test_provenance_missing_meta_backfilled_and_warns_for_legacy(tmp_path, caplog):
    """旧库无 meta（schema_version 缺失）→ 按当前补写；真旧库（有数据）告警放行。"""
    db = str(tmp_path / "nolegacymeta.db")
    s1 = SQLiteStore({"path": db})
    s1.initialize()
    s1.add_node(Node(id="a", name="A", content=""))  # 有数据 → 真旧库
    s1.save()  # 落盘（含 meta）；node 'a' 进 SQLite
    s1.conn.execute("DELETE FROM meta")  # 抹掉出处模拟缺失
    s1.conn.commit()
    s1.shutdown()
    s2 = SQLiteStore({"path": db})
    with caplog.at_level(logging.WARNING):
        s2.initialize()
    meta = s2._read_meta_all()
    assert meta.get("schema_version") == SCHEMA_VERSION  # 补写放行
    assert any("旧库" in r.message for r in caplog.records)


def test_fresh_db_extensions_column_present(tmp_path):
    """新建库 schema 已含 extensions_json 列；再次开库列仍在、不报错。"""
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
    assert "type" in cols_after  # 统一模型 type 列


# ─── 互斥边扩展（与关联边同构：渲染 / 编解码 / 估算）──────────────────────────


def test_mutex_edge_extension_renders_like_assoc():
    """互斥边扩展渲染与关联边同形（主 — 宾 + 片段），type 不影响渲染口径。"""
    edge = Edge(
        source_id="a", target_id="b", type=EDGE_MUTEX,
        extensions={"activity": {"count": 4}},
    )
    out = ContextRenderer.render_relation_edge(
        edge, _nm(), extensions=[ActivityEdgeExt()], purpose="select_facts"
    )
    assert "A — B" in out
    assert "活跃=4" in out


def test_mutex_edge_extensions_sqlite_roundtrip(tmp_path):
    """互斥边扩展 SQLite 编解码保真（与关联边同构）。"""
    db = str(tmp_path / "mutex.db")
    store = SQLiteStore({"path": db})
    store.initialize(edge_extensions={"activity": ActivityEdgeExt()})
    store.add_node(Node(id="fa", name="FA", content="", node_class=CLASS_FACT))
    store.add_node(Node(id="fb", name="FB", content="", node_class=CLASS_FACT))
    store.add_edge("fa", "fb", type=EDGE_MUTEX, extensions={"activity": {"count": 9}})
    store.save_full()
    store.shutdown()

    store2 = SQLiteStore({"path": db})
    store2.initialize(edge_extensions={"activity": ActivityEdgeExt()})
    store2.load()
    mutex = [e for e in store2.get_all_edges() if e.type == EDGE_MUTEX]
    assert len(mutex) == 1
    assert mutex[0].extensions.get("activity", {}).get("count") == 9


def test_estimate_relation_edge_mutex_equals_render():
    """互斥边渲染 == 估算（查询侧一致性，与关联边对称）。"""
    tb = TokenBudget(8000)
    edge = Edge(
        source_id="a", target_id="b", type=EDGE_MUTEX,
        extensions={"activity": {"count": 6}},
    )
    exts = [ActivityEdgeExt()]
    rendered = ContextRenderer.render_relation_edge(edge, _nm(), exts, "select_facts")
    assert tb.estimate_relation_edge(edge, _nm(), exts, "select_facts") == tb.estimate(rendered)

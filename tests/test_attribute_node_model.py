"""attribute_node 模式（无类型关联边 + 属性节点）测试。

覆盖 openspec/changes/attribute-node-model tasks 9.1–9.7：
- 9.1 assoc 边：kind 隔离（C4）、两端反查、去重
- 9.2 attribute 写入：建属性节点 + assoc；字面值内联；role=attribute；content 过长 LLM 压缩（A2）
- 9.3 渲染/估算：render_assoc_edge 无 label；属性节点按节点渲染；估算==渲染（铁律一）
- 9.4 attribute 查询：get_assoc 视图、选关联边补端点、entity-anchored 现推
- 9.5 守门：A1 有 assoc 不挂 root；B3 属性节点不进层级骨架；回滚/去重保 kind=assoc
- 9.6 模式开关：property_graph 默认逐字不变；非法 relation_model 报错
- 9.7 集成：attribute_node write→query 全流程
- 9.8 评测：本期跳过（attribute_node 为用户可选项，非对比用途）
- 9.9 全仓回归：见 pytest 全量
"""

from __future__ import annotations

import pytest

from mcs.core.context_renderer import ContextRenderer
from mcs.core.query_engine import QueryContext, QueryEngine
from mcs.core.token_budget import TokenBudget
from mcs.core.write_pipeline import WritePipeline
from mcs.entities.config import MCSConfig
from mcs.entities.decisions import ConceptDraft, Decision
from mcs.entities.graph import Edge, Node
from mcs.stores.in_memory import InMemoryStore

# ── 测试辅助 ───────────────────────────────────────────────────────

class _MockPM:
    """空插件管理器：所有链返回空，无入口/裁剪/压缩插件。"""

    def get_all(self, t):
        return []

    def get(self, t):
        return None


class _MockLLM:
    """按 purpose 返回预设结果的 LLM。值可为静态值或 () -> 值 的 callable。"""

    def __init__(self, **by_purpose):
        self.by = by_purpose
        self.calls: list[str] = []

    def call(self, purpose, nodes_in=None, free_args=None):
        self.calls.append(purpose)
        resp = self.by.get(purpose)
        return resp() if callable(resp) else resp


def _make(relation_model="attribute_node", llm=None, store=None):
    """构造 (WritePipeline, QueryEngine, store, config) 三件套，共享 store/llm/pm。"""
    cfg = MCSConfig(relation_model=relation_model)
    store = store or InMemoryStore()
    pm = _MockPM()
    tb = TokenBudget(8000)
    llm = llm or _MockLLM()
    qe = QueryEngine(
        store=store, llm=llm, plugin_manager=pm, token_budget=tb,
        relation_model=relation_model,
    )
    wp = WritePipeline(
        store=store, llm=llm, query_engine=qe, plugin_manager=pm,
        token_budget=tb, config=cfg,
    )
    return wp, qe, store, cfg


def _add_nodes(store, specs):
    """specs: [(id, name, content, role)] → 加节点。"""
    for nid, name, content, role in specs:
        store.add_node(Node(id=nid, name=name, content=content, role=role))


# ── 9.1 assoc 边：kind 隔离 / 反查 / 去重 ──────────────────────────

def test_assoc_edge_kind_isolation_c4():
    """get_facts 不返回 assoc、get_assoc 不返回 fact（C4 隔离）。"""
    store = InMemoryStore()
    _add_nodes(store, [("a", "A", "ca", "concept"), ("b", "B", "cb", "concept")])
    store.add_edge("a", "b", kind="fact", label="likes")
    store.add_edge("a", "b", kind="assoc")
    between = store.get_edges_between("a", "b")
    assert {e.kind for e in between} == {"fact", "assoc"}
    assert all(e.kind == "fact" for e in store.get_facts("a"))
    assert all(e.kind == "assoc" for e in store.get_assoc("a"))
    assert store.get_facts("a") and store.get_assoc("a")


def test_assoc_two_end_reverse_lookup():
    """assoc 边两端都可达（反查）：A—R—B，get_assoc(A/B/R) 都命中。"""
    store = InMemoryStore()
    _add_nodes(store, [("a", "A", "ca", "concept"), ("b", "B", "cb", "concept"),
                       ("r", "R", "rel", "attribute")])
    store.add_edge("a", "r", kind="assoc")
    store.add_edge("r", "b", kind="assoc")
    assert any(e.target_id == "r" for e in store.get_assoc("a"))
    assert any(e.source_id == "r" for e in store.get_assoc("b"))
    assert {e.source_id + ">" + e.target_id for e in store.get_assoc("r")} == {"a>r", "r>b"}


def test_assoc_dedup_by_pair():
    """同一对节点 (source,target) 的 assoc 边只存一份。"""
    store = InMemoryStore()
    _add_nodes(store, [("a", "A", "ca", "concept"), ("b", "B", "cb", "concept")])
    e1 = store.add_edge("a", "b", kind="assoc")
    e2 = store.add_edge("a", "b", kind="assoc")
    assert e1 == e2
    assert len([e for e in store.get_all_edges() if e.kind == "assoc"]) == 1


def test_assoc_property_graph_returns_empty():
    """property_graph 模式不建 assoc 边 → get_assoc 返回空、不报错（2.5）。"""
    store = InMemoryStore()
    _add_nodes(store, [("a", "A", "ca", "concept"), ("b", "B", "cb", "concept")])
    store.add_edge("a", "b", kind="fact", label="likes")
    assert store.get_assoc("a") == []


# ── 9.2 attribute 写入 ─────────────────────────────────────────────

def test_attribute_write_concept_concept_two_assoc():
    """概念-概念关系：建属性节点 + 2 条 assoc，无 fact。"""
    wp, qe, store, cfg = _make("attribute_node")
    _add_nodes(store, [("a", "小明", "人物", "concept"), ("b", "苹果", "水果", "concept")])
    wp._apply_decisions([
        Decision(action="create_attribute", attr_name="喜欢",
                 attr_content="小明喜欢苹果",
                 assoc_to=[{"target_id": "a"}, {"target_id": "b"}]),
    ])
    attrs = [n for n in store.get_all_nodes() if n.role == "attribute"]
    assert len(attrs) == 1 and attrs[0].content == "小明喜欢苹果"
    assoc = {e.source_id + ">" + e.target_id for e in store.get_assoc(attrs[0].id)}
    assert assoc == {attrs[0].id + ">a", attrs[0].id + ">b"}
    assert store.get_facts("a") == []


def test_attribute_write_literal_inline_single_assoc():
    """概念-字面值：建属性节点（content 内联值）+ 1 条 assoc（单端点）。"""
    wp, qe, store, cfg = _make("attribute_node")
    _add_nodes(store, [("a", "苹果", "水果", "concept")])
    wp._apply_decisions([
        Decision(action="create_attribute", attr_name="苹果的颜色",
                 attr_content="苹果的颜色是红色",
                 assoc_to=[{"target_id": "a"}]),
    ])
    attrs = [n for n in store.get_all_nodes() if n.role == "attribute"]
    assert len(attrs) == 1 and "红色" in attrs[0].content
    assert len(store.get_assoc(attrs[0].id)) == 1
    assert len(store.get_assoc("a")) == 1


def test_attribute_content_compressed_a2():
    """属性节点 content 过长 → LLM 压缩到上限（A2）。"""
    long_content = "这是一段非常长的属性节点内容" * 20  # 远超上限
    llm = _MockLLM(gen_summary="压缩后的短说法")
    cfg = MCSConfig(relation_model="attribute_node", attribute_content_max=50)
    store = InMemoryStore()
    qe = QueryEngine(store=store, llm=llm, plugin_manager=_MockPM(),
                     token_budget=TokenBudget(8000), relation_model="attribute_node")
    wp = WritePipeline(store=store, llm=llm, query_engine=qe, plugin_manager=_MockPM(),
                       token_budget=TokenBudget(8000), config=cfg)
    wp._apply_decisions([
        Decision(action="create_attribute", attr_name="长属性",
                 attr_content=long_content, assoc_to=[]),
    ])
    attrs = [n for n in store.get_all_nodes() if n.role == "attribute"]
    assert len(attrs) == 1
    assert attrs[0].content == "压缩后的短说法"
    assert "gen_summary" in llm.calls


def test_attribute_content_compression_failure_keeps_original():
    """LLM 压缩异常 → 保留原文（边界：不崩、不丢）。"""

    def _raise(*a, **k):
        raise RuntimeError("boom")

    llm = _MockLLM(gen_summary=_raise)
    cfg = MCSConfig(relation_model="attribute_node", attribute_content_max=10)
    store = InMemoryStore()
    qe = QueryEngine(store=store, llm=llm, plugin_manager=_MockPM(),
                     token_budget=TokenBudget(8000), relation_model="attribute_node")
    wp = WritePipeline(store=store, llm=llm, query_engine=qe, plugin_manager=_MockPM(),
                       token_budget=TokenBudget(8000), config=cfg)
    wp._apply_decisions([
        Decision(action="create_attribute", attr_name="x",
                 attr_content="原始长内容" * 5, assoc_to=[]),
    ])
    attrs = [n for n in store.get_all_nodes() if n.role == "attribute"]
    assert len(attrs) == 1 and attrs[0].content.startswith("原始长内容")


def test_empty_create_attribute_dropped():
    """空 create_attribute（无 content 无端点）被 _sanitize 丢弃（边界）。"""
    wp, qe, store, cfg = _make("attribute_node")
    cleaned = wp._sanitize_decisions([
        Decision(action="create_attribute", attr_name=None, attr_content=None,
                 assoc_to=[], assoc_to_names=[]),
    ])
    assert cleaned == []


def test_attribute_same_name_dedup():
    """同名属性节点去重复用：两次 create_attribute 同名 → 一个节点、两端点都连。"""
    wp, qe, store, cfg = _make("attribute_node")
    _add_nodes(store, [("a", "A", "ca", "concept"), ("b", "B", "cb", "concept")])
    wp._apply_decisions([
        Decision(action="create_attribute", attr_name="关系", attr_content="c1",
                 assoc_to=[{"target_id": "a"}]),
        Decision(action="create_attribute", attr_name="关系", attr_content="c2",
                 assoc_to=[{"target_id": "b"}]),
    ])
    attrs = [n for n in store.get_all_nodes() if n.role == "attribute"]
    assert len(attrs) == 1
    assert {e.target_id for e in store.get_assoc(attrs[0].id)} == {"a", "b"}


# ── 9.3 渲染 / 估算（铁律一） ──────────────────────────────────────

def test_render_assoc_edge_no_label():
    edge = Edge(source_id="a", target_id="b", kind="assoc")
    nm = {"a": Node(id="a", name="小明", content=""),
          "b": Node(id="b", name="苹果", content="")}
    assert ContextRenderer.render_assoc_edge(edge, nm) == "小明 — 苹果"


def test_render_facts_mode_switch():
    """render_facts mode 切换：attribute 无 label、property_graph 有 label；默认==pg。"""
    cr = ContextRenderer()
    a = Node(id="a", name="小明", content="人物")
    b = Node(id="b", name="苹果", content="水果")
    e_assoc = Edge(source_id="a", target_id="b", kind="assoc")
    e_fact = Edge(source_id="a", target_id="b", kind="fact", label="喜欢")
    r_attr = cr.render_facts([a, b], [e_assoc], mode="attribute_node")
    r_pg = cr.render_facts([a, b], [e_fact], mode="property_graph")
    assert "—" in r_attr and "喜欢" not in r_attr
    assert "喜欢" in r_pg
    assert cr.render_facts([a, b], [e_fact]) == r_pg  # 默认 == property_graph


def test_estimate_equals_render_assoc_iron_law():
    """估算 == 渲染（铁律一）：assoc 边估算复用 render_assoc_edge；活跃视图同口径。"""
    tb = TokenBudget(8000)
    a = Node(id="a", name="小明", content="人物")
    r = Node(id="r", name="喜欢", content="小明喜欢苹果", role="attribute")
    e = Edge(source_id="a", target_id="r", kind="assoc")
    nm = {"a": a, "r": r}
    # 单边：estimate_assoc_edge == estimate(render_assoc_edge)
    assert tb.estimate_assoc_edge(e, nm) == tb.estimate(ContextRenderer.render_assoc_edge(e, nm))
    # 活跃视图 = 节点 a + 边 e（边用 estimate_assoc_edge 同口径）
    view_est = tb.estimate_active_view(a, [], [e], node_map=nm, mode="attribute_node")
    assert view_est == tb.estimate_node(a) + tb.estimate_assoc_edge(e, nm)


def test_estimate_active_view_assoc_shorter_than_fact():
    """同结构下，attribute 模式（assoc 无 label）估算 < property_graph（fact 带 label）。"""
    tb = TokenBudget(8000)
    a = Node(id="a", name="小明", content="人物")
    b = Node(id="b", name="苹果", content="水果")
    nm = {"a": a, "b": b}
    e_assoc = Edge(source_id="a", target_id="b", kind="assoc")
    e_fact = Edge(source_id="a", target_id="b", kind="fact", label="喜欢")
    v_attr = tb.estimate_active_view(a, [], [e_assoc], node_map=nm, mode="attribute_node")
    v_pg = tb.estimate_active_view(a, [], [e_fact], node_map=nm, mode="property_graph")
    assert v_attr < v_pg


# ── 9.4 attribute 查询 ─────────────────────────────────────────────

def test_attribute_query_traverse_pulls_attr_node():
    """attribute 查询：get_assoc 视图、选关联边、属性节点补入。"""
    store = InMemoryStore()
    _add_nodes(store, [("a", "小明", "人物", "concept"), ("b", "苹果", "水果", "concept"),
                       ("r", "喜欢", "小明喜欢苹果", "attribute")])
    store.add_edge("a", "r", kind="assoc")
    store.add_edge("r", "b", kind="assoc")
    llm = _MockLLM(select_facts=[3])
    qe = QueryEngine(store=store, llm=llm, plugin_manager=_MockPM(),
                     token_budget=TokenBudget(8000), relation_model="attribute_node")
    nodes, edges = qe._traverse([store.get_node("a")], "小明喜欢苹果吗", QueryContext())
    assert "r" in {n.id for n in nodes}  # 属性节点经关联边补入
    assert all(e.kind == "assoc" for e in edges)


def test_attribute_query_entity_anchored_polarity():
    """entity-anchored：问"讨厌"但图里是"喜欢"，仍反查到属性节点（不因无关系短路）。"""
    store = InMemoryStore()
    _add_nodes(store, [("a", "小明", "人物", "concept"), ("b", "苹果", "水果", "concept"),
                       ("r", "喜欢", "小明喜欢苹果", "attribute")])
    store.add_edge("a", "r", kind="assoc")
    store.add_edge("r", "b", kind="assoc")
    llm = _MockLLM(select_facts=[3])
    qe = QueryEngine(store=store, llm=llm, plugin_manager=_MockPM(),
                     token_budget=TokenBudget(8000), relation_model="attribute_node")
    nodes, _ = qe._traverse([store.get_node("a")], "小明讨厌苹果吗", QueryContext())
    assert any(n.role == "attribute" for n in nodes)


# ── 9.5 守门 ───────────────────────────────────────────────────────

def _run_fanout(store, changed, relation_model):
    from mcs.core.plugin_manager import PluginContext
    from mcs.plugins.maintenance.fanout_reducer import FanoutReducerPlugin
    plug = FanoutReducerPlugin({"maintain_root": True})
    plug.initialize(PluginContext(
        store=store, config=MCSConfig(relation_model=relation_model),
        token_budget=TokenBudget(8000), context_renderer=None, plugin_manager=None))
    plug.run(changed, store, lambda **kw: None)


def test_a1_orphan_check_attribute_mode():
    """A1：attribute 模式有 assoc 关联的概念不挂 root，零关联才挂。"""
    from mcs.plugins.maintenance.fanout_reducer import SEED_ROOT_ID
    store = InMemoryStore()
    _add_nodes(store, [("a", "A", "ca", "concept"), ("b", "B", "cb", "concept"),
                       ("r", "R", "rel", "attribute")])
    store.add_edge("a", "r", kind="assoc")  # A 有关系
    _run_fanout(store, [store.get_node("a"), store.get_node("b")], "attribute_node")
    rc = {n.id for n in store.get_out_hierarchy(SEED_ROOT_ID)}
    assert "a" not in rc and "b" in rc


def test_a1_property_graph_baseline_zero_change():
    """A1：property_graph 模式 get_assoc 恒空 → 孤儿判定等价原 get_facts 行为。"""
    from mcs.plugins.maintenance.fanout_reducer import SEED_ROOT_ID
    store = InMemoryStore()
    _add_nodes(store, [("a", "A", "ca", "concept"), ("b", "B", "cb", "concept"),
                       ("c", "C", "cc", "concept")])
    store.add_edge("a", "c", kind="fact", label="rel")  # A 有 fact（B 保持孤立）
    _run_fanout(store, [store.get_node("a"), store.get_node("b")], "property_graph")
    rc = {n.id for n in store.get_out_hierarchy(SEED_ROOT_ID)}
    assert "a" not in rc and "b" in rc


def test_b3_attribute_node_not_in_hierarchy():
    """B3：属性节点经 assoc 连接，不进 get_out_hierarchy、不参与 fanout 收敛。"""
    store = InMemoryStore()
    _add_nodes(store, [("a", "A", "ca", "concept"), ("r", "R", "rel", "attribute")])
    store.add_edge("a", "r", kind="assoc")
    assert store.get_node("r") not in store.get_out_hierarchy("a")
    assert store.get_out_hierarchy("r") == []


def test_snapshot_restore_preserves_assoc():
    """回滚/快照保 kind=assoc：snapshot→delete→restore 后 assoc 反查恢复。"""
    store = InMemoryStore()
    _add_nodes(store, [("a", "A", "ca", "concept"), ("r", "R", "rel", "attribute")])
    eid = store.add_edge("a", "r", kind="assoc")
    snap = store.snapshot()
    store.delete_edge(eid)
    assert store.get_assoc("a") == []
    store.restore(snap)
    assert any(e.id == eid and e.kind == "assoc" for e in store.get_assoc("a"))


# ── 9.6 模式开关 ───────────────────────────────────────────────────

def test_property_graph_default_relation_model():
    assert MCSConfig().relation_model == "property_graph"
    assert MCSConfig.knowledge_graph().relation_model == "property_graph"


def test_invalid_relation_model_rejected():
    with pytest.raises(ValueError):
        MCSConfig(relation_model="bogus")


def test_property_graph_write_uses_fact_edges():
    """property_graph 模式 create 决策建 fact 边（基线，逐字不变）。"""
    wp, qe, store, cfg = _make("property_graph")
    _add_nodes(store, [("x", "X", "cx", "concept")])
    wp._apply_decisions([
        Decision(action="create", concept=ConceptDraft(name="Y", content="cy"),
                 edges_to=[{"target_id": "x", "label": "属于"}]),
    ])
    y = next(n for n in store.get_all_nodes() if n.name == "Y")
    facts = store.get_facts(y.id)
    assert len(facts) == 1 and facts[0].kind == "fact" and facts[0].label == "属于"
    assert store.get_assoc(y.id) == []


def test_attribute_create_with_edges_to_builds_no_fact():
    """防御：attribute 模式 create 决策即便带 edges_to 也不建 fact 边（核心自洽）。"""
    wp, qe, store, cfg = _make("attribute_node")
    _add_nodes(store, [("x", "X", "cx", "concept")])
    wp._apply_decisions([
        Decision(action="create", concept=ConceptDraft(name="Y", content="cy"),
                 edges_to=[{"target_id": "x", "label": "属于"}]),
    ])
    y = next(n for n in store.get_all_nodes() if n.name == "Y")
    assert store.get_facts(y.id) == []
    assert store.get_assoc(y.id) == []


def test_property_graph_no_judge_relations_override():
    """property_graph 预设不注入 judge_relations override（用默认 prompt）。"""
    assert "judge_relations" not in MCSConfig.knowledge_graph().prompt_overrides
    assert "judge_relations" in MCSConfig.knowledge_graph(relation_model="attribute_node").prompt_overrides


# ── 9.7 集成：attribute_node write→query 全流程 ───────────────────

def test_write_query_integration_attribute_node():
    """ingest（mock LLM 抽概念+判关系）→ 建属性节点+assoc → query 反查选中。"""
    store = InMemoryStore()
    llm = _MockLLM(
        extract_concepts=[ConceptDraft(name="小明", content="人物"),
                          ConceptDraft(name="苹果", content="水果")],
        judge_relations=[
            Decision(action="create", concept=ConceptDraft(name="小明", content="人物")),
            Decision(action="create", concept=ConceptDraft(name="苹果", content="水果")),
            Decision(action="create_attribute", attr_name="喜欢",
                     attr_content="小明喜欢苹果",
                     assoc_to_names=[{"target_name": "小明"}, {"target_name": "苹果"}]),
        ],
        select_facts=[3],
    )
    wp, qe, store, cfg = _make("attribute_node", llm=llm, store=store)
    wp.ingest("小明喜欢苹果")
    # 写入校验：2 概念 + 1 属性节点 + 2 assoc + 0 fact
    attrs = [n for n in store.get_all_nodes() if n.role == "attribute"]
    assert len(attrs) == 1 and attrs[0].content == "小明喜欢苹果"
    concepts = [n for n in store.get_all_nodes() if n.role == "concept"]
    assert {n.name for n in concepts} == {"小明", "苹果"}
    assert len([e for e in store.get_all_edges() if e.kind == "assoc"]) == 2
    assert not [e for e in store.get_all_edges() if e.kind == "fact"]
    # 查询校验：从小明出发，反查到属性节点、选中 assoc 边
    ming = next(n for n in concepts if n.name == "小明")
    nodes, edges = qe._traverse([ming], "小明喜欢苹果吗", QueryContext())
    assert any(n.role == "attribute" for n in nodes)
    assert all(e.kind == "assoc" for e in edges)

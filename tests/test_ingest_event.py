"""WritePipeline.ingest_event 测试：事件规则入库 + 背书边 + 载重规则。"""

from __future__ import annotations

from mcs.core.plugin_manager import PluginManager
from mcs.core.query_engine import QueryEngine
from mcs.core.token_budget import TokenBudget
from mcs.core.write_pipeline import WritePipeline
from mcs.entities.decisions import EventData
from mcs.entities.graph import CLASS_CONCEPT, CLASS_EVENT, EDGE_ASSOC, Node
from mcs.stores.in_memory import InMemoryStore


def _make_pipeline(store=None, mock_llm=None):
    from tests.conftest import MockLLM
    store = store or InMemoryStore()
    llm = mock_llm or MockLLM()
    pm = PluginManager()
    pm.register(llm)
    tb = TokenBudget(8000)
    qe = QueryEngine(store=store, llm=llm, plugin_manager=pm, token_budget=tb)
    return WritePipeline(
        store=store, llm=llm, query_engine=qe, plugin_manager=pm, token_budget=tb,
    )


def test_ingest_event_creates_event_node():
    """ingest_event 创建 CLASS_EVENT 节点。"""
    g = InMemoryStore()
    wp = _make_pipeline(g)
    node = wp.ingest_event(EventData(name="用户对话", content="用户说了些什么"))
    assert node.node_class == CLASS_EVENT
    assert node.name == "用户对话"
    assert g.get_node(node.id) is not None


def test_ingest_event_creates_endorsement_edges():
    """对每个 target_id 创建 事件→目标 的关联边（背书）。"""
    g = InMemoryStore()
    fact = Node(id="f1", name="某事实", content="某事实", node_class="事实")
    concept = Node(id="c1", name="某概念", content="某概念", node_class="概念")
    g.add_node(fact)
    g.add_node(concept)

    wp = _make_pipeline(g)
    node = wp.ingest_event(EventData(
        name="事件", content="发生了某事",
        target_ids=["f1", "c1"],
    ))
    # 事件→事实 和 事件→概念 都应存在
    assoc = [e for e in g.get_relations(node.id) if e.type == EDGE_ASSOC]
    targets = {e.target_id for e in assoc}
    assert "f1" in targets
    assert "c1" in targets


def test_event_not_retrieved_by_core_get_relations():
    """核心节点 get_relations 不含事件背书边（载重规则）。"""
    g = InMemoryStore()
    fact = Node(id="f1", name="某事实", content="某事实", node_class="事实")
    g.add_node(fact)

    wp = _make_pipeline(g)
    event = wp.ingest_event(EventData(
        name="事件", content="发生了某事",
        target_ids=["f1"],
    ))
    # 事件→事实 边存在
    event_assoc = [e for e in g.get_relations(event.id) if e.type == EDGE_ASSOC]
    assert any(e.target_id == "f1" for e in event_assoc)

    # 核心节点侧 get_relations 应过滤事件边
    fact_assoc = [e for e in g.get_relations("f1") if e.type == EDGE_ASSOC]
    assert not any(e.source_id == event.id for e in fact_assoc)


def test_event_side_still_reaches_core():
    """事件侧 get_relations 能看到背书边。"""
    g = InMemoryStore()
    fact = Node(id="f1", name="某事实", content="某事实", node_class="事实")
    g.add_node(fact)

    wp = _make_pipeline(g)
    event = wp.ingest_event(EventData(
        name="事件", content="发生了某事",
        target_ids=["f1"],
    ))
    assoc = [e for e in g.get_relations(event.id) if e.type == EDGE_ASSOC]
    assert any(e.target_id == "f1" for e in assoc)


def test_ingest_event_with_timestamp():
    """timestamp 存入 extensions["event_meta"]["timestamp"]。"""
    g = InMemoryStore()
    wp = _make_pipeline(g)
    node = wp.ingest_event(EventData(
        name="事件", content="内容",
        timestamp="2026-06-20T10:00:00Z",
    ))
    assert node.extensions["event_meta"]["timestamp"] == "2026-06-20T10:00:00Z"


def test_ingest_event_no_targets():
    """无 target_ids 时只建事件节点、不建边。"""
    g = InMemoryStore()
    wp = _make_pipeline(g)
    node = wp.ingest_event(EventData(name="孤立事件", content="没有目标"))
    assert node.node_class == CLASS_EVENT
    assert g.get_relations(node.id) == []


def test_ingest_event_skips_nonexistent_targets():
    """target_ids 中不存在的节点跳过（不建悬空边）。"""
    g = InMemoryStore()
    wp = _make_pipeline(g)
    node = wp.ingest_event(EventData(
        name="事件", content="内容",
        target_ids=["nonexistent"],
    ))
    assert g.get_relations(node.id) == []

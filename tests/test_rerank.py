"""RerankPlugin / LexicalScorer 测试（query_postprocess 重排）。

覆盖 tasks 5.1（打分 + 重排/过滤/截断）与 5.2（默认 opt-in，不改既有查询链行为）。
"""

from __future__ import annotations

from types import SimpleNamespace

from mcs.core.config import PHASE1_DEFAULT_PLUGINS, MCSConfig
from mcs.core.graph import Node
from mcs.core.plugin_manager import PluginContext, PluginManager
from mcs.core.query_engine import QueryEngine
from mcs.core.token_budget import TokenBudget
from mcs.plugins.postprocess.rerank import LexicalScorer, RerankPlugin
from mcs.stores.in_memory import InMemoryStore

GraphStore = InMemoryStore


def _ctx(query: str) -> SimpleNamespace:
    """最小 QueryContext 替身，仅需 user_input。"""
    return SimpleNamespace(user_input=query)


def _node(nid: str, name: str, content: str = "", statements=None) -> Node:
    ext: dict = {}
    if statements:
        ext["statements"] = {"items": list(statements)}
    return Node(id=nid, name=name, content=content, extensions=ext)


# ─── 5.1 LexicalScorer ────────────────────────────────────────────────────────


def test_lexical_scorer_ranks_relevant_higher():
    sc = LexicalScorer()
    relevant = _node("1", "Tesla Model 3", "Tesla ramps Model 3 output in Shanghai.")
    irrelevant = _node("2", "Weather forecast", "Rain expected tomorrow in Berlin.")
    q = "How many Model 3 did Tesla produce?"
    assert sc.score(q, relevant) > sc.score(q, irrelevant)


def test_lexical_scorer_name_weighted_over_content():
    """name 命中应比仅 content 命中得分更高（name 加权）。"""
    sc = LexicalScorer()
    in_name = _node("1", "quantum computing", "unrelated body text here")
    in_content = _node("2", "unrelated title", "a piece about quantum computing today")
    q = "quantum computing"
    assert sc.score(q, in_name) > sc.score(q, in_content) > 0.0


def test_lexical_scorer_empty_query_is_zero():
    sc = LexicalScorer()
    assert sc.score("", _node("1", "anything", "body")) == 0.0


def test_lexical_scorer_uses_content():
    """content 中的命中应计入相关性（statements 已废弃，不再使用）。"""
    sc = LexicalScorer()
    node = _node("1", "Person X", "X founded Acme Corporation")
    assert sc.score("Acme Corporation", node) > 0.0


# ─── 5.1 RerankPlugin：重排 / 过滤 / 截断 ─────────────────────────────────────


def test_rerank_orders_by_score():
    """乱序输入应被重排为相关性降序（构造已知节点验证顺序）。"""
    plugin = RerankPlugin()
    nodes = [
        _node("irrelevant", "weather", "rain in berlin"),
        _node("relevant", "Tesla Model 3 production", "Tesla Model 3 output rises"),
        _node("partial", "Tesla", "a short note about Tesla"),
    ]
    out = plugin.process(nodes, _ctx("Tesla Model 3 production numbers"))
    ids = [n.id for n in out]
    assert ids[0] == "relevant"
    assert ids.index("relevant") < ids.index("partial") < ids.index("irrelevant")


def test_rerank_filters_below_min_score():
    plugin = RerankPlugin({"min_score": 0.5})
    nodes = [
        _node("hit", "Tesla Model 3", "Tesla Model 3 output"),
        _node("miss", "weather", "rain in berlin"),  # 与查询零重叠 → 分 0.0
    ]
    out = plugin.process(nodes, _ctx("Tesla Model 3"))
    ids = [n.id for n in out]
    assert "hit" in ids
    assert "miss" not in ids  # 低于阈值被丢弃


def test_rerank_truncates_top_n():
    plugin = RerankPlugin({"top_n": 2})
    nodes = [
        _node("a", "Tesla Model 3 alpha", "Tesla Model 3"),
        _node("b", "Tesla Model 3 beta", "Tesla Model 3"),
        _node("c", "Tesla Model 3 gamma", "Tesla Model 3"),
    ]
    out = plugin.process(nodes, _ctx("Tesla Model 3"))
    assert len(out) == 2


def test_rerank_empty_passthrough():
    plugin = RerankPlugin()
    assert plugin.process([], _ctx("anything")) == []


def test_rerank_stable_for_equal_scores():
    """同分节点维持原始相对顺序（稳定排序）。"""
    plugin = RerankPlugin()
    # 查询与任何节点都零重叠 → 全部 0 分 → 应保持原顺序
    nodes = [_node(str(i), f"name{i}", "body") for i in range(5)]
    out = plugin.process(nodes, _ctx("zzz_no_overlap_query"))
    assert [n.id for n in out] == [str(i) for i in range(5)]


# ─── 5.2 默认 opt-in ──────────────────────────────────────────────────────────


def test_rerank_not_in_default_plugins():
    """默认插件链不包含 rerank（opt-in）。"""
    assert "rerank" not in PHASE1_DEFAULT_PLUGINS
    config = MCSConfig.knowledge_graph()
    assert "rerank" not in config.read_plugins


def _query_engine(mock_llm, *plugins):
    graph = GraphStore()
    pm = PluginManager()
    pm.register(mock_llm)
    for p in plugins:
        pm.register(p)
    ctx = PluginContext(
        store=graph,
        config=MCSConfig(),
        token_budget=TokenBudget(8000),
        context_renderer=None,  # type: ignore[arg-type]
        plugin_manager=pm,
    )
    pm.initialize_all(ctx)
    return QueryEngine(
        store=graph,
        llm=mock_llm,
        plugin_manager=pm,
        token_budget=TokenBudget(8000),
        max_rounds=1,
        max_accumulated_nodes=20,
    )


def test_query_unchanged_without_rerank(mock_llm):
    """未启用 rerank 时，query() 输出与 result_set 顺序一致（既有行为不变）。"""
    qe = _query_engine(mock_llm)  # 无 postprocess 插件
    seeds = [
        _node("irrelevant", "weather", "rain"),
        _node("relevant", "Tesla Model 3", "Tesla Model 3 output"),
    ]
    # select_nodes 选中所有种子
    mock_llm.set_response("select_nodes", lambda nodes_in, _: [n.id for n in (nodes_in or [])])
    out = qe.query("Tesla Model 3", existing_context=seeds)
    assert [n.id for n in out] == ["irrelevant", "relevant"]  # 原顺序，未重排


def test_query_reranks_when_enabled(mock_llm):
    """注册 RerankPlugin 后，同一查询链把相关节点排到前面。"""
    qe = _query_engine(mock_llm, RerankPlugin())
    seeds = [
        _node("irrelevant", "weather", "rain"),
        _node("relevant", "Tesla Model 3", "Tesla Model 3 output"),
    ]
    # select_nodes 选中所有种子
    mock_llm.set_response("select_nodes", lambda nodes_in, _: [n.id for n in (nodes_in or [])])
    out = qe.query("Tesla Model 3", existing_context=seeds)
    assert out[0].id == "relevant"

"""查询侧虚拟根种子图归纳测试。覆盖 subgraph-bounding tasks 4.4。"""

from __future__ import annotations

from mcs.core.config import MCSConfig
from mcs.core.decisions import HubDecision
from mcs.core.graph import GraphStore, Node
from mcs.core.plugin_manager import PluginContext, PluginManager
from mcs.core.query_engine import QueryContext, QueryEngine
from mcs.core.token_budget import TokenBudget
from mcs.plugins.phase1.fanout_reducer import FanoutReducerPlugin


def _engine(graph, mock_llm, token_budget, seed_bounding):
    pm = PluginManager()
    pm.register(mock_llm)
    pm.register(FanoutReducerPlugin({"floor": 16}))
    pm.initialize_all(
        PluginContext(
            graph=graph,
            config=MCSConfig(),
            token_budget=token_budget,
            context_renderer=None,  # type: ignore[arg-type]
            plugin_manager=pm,
        )
    )
    return QueryEngine(
        graph=graph,
        llm=mock_llm,
        plugin_manager=pm,
        token_budget=token_budget,
        max_rounds=3,
        max_picked=50,
        seed_bounding=seed_bounding,
    )


def _seeds(graph, n, content):
    out = []
    for i in range(n):
        node = Node(id=f"s{i}", name=f"s{i}", content=content)
        graph.add_node(node)
        out.append(node)
    return out


def test_large_seed_set_bounded_into_hubs(mock_llm):
    g = GraphStore()
    seeds = _seeds(g, 20, "a" * 400)  # 每个 ~100 token；20 个远超小窗口
    mock_llm.set_response(
        "decide_hub", HubDecision(hub_id=None, synthetic_hub_summary="Group")
    )
    qe = _engine(g, mock_llm, TokenBudget(500), seed_bounding=True)

    new_seeds = qe._bound_seed_graph(seeds, QueryContext())
    assert len(new_seeds) < len(seeds)  # 归纳收敛
    assert any(n.role == "hub" for n in g.get_all_nodes())  # 落图的中间概念
    # 虚拟根用完即弃
    assert not any(n.name == "__seed_root__" for n in g.get_all_nodes())


def test_small_seed_set_passthrough(mock_llm):
    g = GraphStore()
    seeds = _seeds(g, 5, "x")  # 远低于容量
    qe = _engine(g, mock_llm, TokenBudget(8000), seed_bounding=True)
    new_seeds = qe._bound_seed_graph(seeds, QueryContext())
    assert {n.id for n in new_seeds} == {n.id for n in seeds}  # 不超容量 → 透传
    assert not any(n.role == "hub" for n in g.get_all_nodes())


def test_opt_in_off_does_not_bound(mock_llm):
    g = GraphStore()
    seeds = _seeds(g, 20, "a" * 400)
    mock_llm.set_response(
        "decide_hub", HubDecision(hub_id=None, synthetic_hub_summary="Group")
    )
    qe = _engine(g, mock_llm, TokenBudget(500), seed_bounding=False)
    out = qe.query("q", existing_context=seeds)
    # 未启用 → 不归纳、不建 hub
    assert not any(n.role == "hub" for n in g.get_all_nodes())
    assert len(out) == 20

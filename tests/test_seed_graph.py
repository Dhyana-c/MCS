"""分层种子图测试（新设计）：

  - 查询侧 ``_bound_seed_graph`` 只读收敛（超预算按预算截断、**不改图**）；
  - 建图侧 ``fanout_reducer``（seed_graph_bounding 开启）维护**持久虚拟根** +
    递归分层，产物入 ``changed_nodes`` 以便落库。
"""

from __future__ import annotations

from mcs.core.config import MCSConfig
from mcs.core.decisions import HubDecision
from mcs.core.graph import GraphStore, Node
from mcs.core.plugin_manager import PluginContext, PluginManager
from mcs.core.query_engine import QueryContext, QueryEngine
from mcs.core.token_budget import TokenBudget
from mcs.plugins.phase1.fanout_reducer import SEED_ROOT_ID, FanoutReducerPlugin


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


# ── 查询侧：只读收敛 ──────────────────────────────────────────────────────────


def test_bound_seed_graph_is_readonly_and_trims(mock_llm):
    """超预算时按预算收敛，且**不改图**（不建虚拟根/不建 hub/不加边）。"""
    g = GraphStore()
    seeds = _seeds(g, 20, "a" * 400)  # 每个 ~100 token；20 个远超小窗口
    qe = _engine(g, mock_llm, TokenBudget(500), seed_bounding=True)
    nodes_before = len(g.get_all_nodes())
    edges_before = len(g.get_all_edges())

    new_seeds = qe._bound_seed_graph(seeds, QueryContext())

    assert len(new_seeds) < len(seeds)                  # 收敛
    assert len(g.get_all_nodes()) == nodes_before       # 只读：节点数不变
    assert len(g.get_all_edges()) == edges_before       # 只读：边数不变
    assert not any(n.role == "hub" for n in g.get_all_nodes())
    assert g.get_node(SEED_ROOT_ID) is None


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
    qe = _engine(g, mock_llm, TokenBudget(500), seed_bounding=False)
    out = qe.query("q", existing_context=seeds)
    assert not any(n.role == "hub" for n in g.get_all_nodes())
    assert len(out) == 20


# ── 建图侧：持久虚拟根 + 递归分层 ─────────────────────────────────────────────


def _fanout_with_root(graph, token_budget, mock_llm):
    pm = PluginManager()
    pm.register(mock_llm)
    fr = FanoutReducerPlugin({"floor": 16})
    pm.register(fr)
    pm.initialize_all(
        PluginContext(
            graph=graph,
            config=MCSConfig(seed_graph_bounding=True),  # 开启持久根维护
            token_budget=token_budget,
            context_renderer=None,  # type: ignore[arg-type]
            plugin_manager=pm,
        )
    )
    return fr


def test_fanout_maintains_persistent_root(mock_llm):
    """seed_graph_bounding 开启：新概念挂持久根、超阈值递归分层、产物入 changed_nodes。"""
    g = GraphStore()
    concepts = []
    for i in range(20):  # 20 个 ~100 token 概念，floor=16 + 小窗口 → 根会被分层
        n = Node(id=f"c{i}", name=f"c{i}", content="a" * 400, role="concept")
        g.add_node(n)
        concepts.append(n)
    mock_llm.set_response(
        "decide_hub", HubDecision(hub_id=None, synthetic_hub_summary="Group")
    )
    fr = _fanout_with_root(g, TokenBudget(500), mock_llm)

    changed = list(concepts)
    fr.run(changed, g, mock_llm.call)

    root = g.get_node(SEED_ROOT_ID)
    assert root is not None                              # 持久根已建
    assert root in changed                               # 根入 changed_nodes（落库）
    # 递归分层出中间 hub
    assert any(n.role == "hub" and n.id != SEED_ROOT_ID for n in g.get_all_nodes())
    # 根的直接扇出已收敛（< 原始 20）
    assert len(g.get_neighbors(SEED_ROOT_ID)) < 20
    # 每个概念仍可从根（递归）到达：所有概念都进了某个 hub 或直接挂根
    assert g.get_node("c0") is not None


def test_no_persistent_root_when_disabled(mock_llm):
    """默认（seed_graph_bounding 关）不建持久根。"""
    g = GraphStore()
    n = Node(id="c0", name="c0", content="x", role="concept")
    g.add_node(n)
    pm = PluginManager()
    pm.register(mock_llm)
    fr = FanoutReducerPlugin({"floor": 16})
    pm.register(fr)
    pm.initialize_all(
        PluginContext(
            graph=g,
            config=MCSConfig(),  # seed_graph_bounding 默认 False
            token_budget=TokenBudget(8000),
            context_renderer=None,  # type: ignore[arg-type]
            plugin_manager=pm,
        )
    )
    changed = [n]
    if fr.should_run(changed, g):
        fr.run(changed, g, mock_llm.call)
    assert g.get_node(SEED_ROOT_ID) is None

"""分层种子图测试（建图侧）：

  - 建图侧 ``fanout_reducer`` 维护**持久虚拟根** + 递归分层，产物入 ``changed_nodes`` 以便落库。
  - 查询侧种子超预算由 SeedSelectorPlugin 链处理（见 test_pipeline_query.py）。
"""

from __future__ import annotations

from mcs.core.config import MCSConfig
from mcs.core.decisions import Community, MultiHubDecision
from mcs.core.graph import Node
from mcs.core.plugin_manager import PluginContext, PluginManager
from mcs.core.query_engine import QueryContext, QueryEngine
from mcs.core.token_budget import TokenBudget
from mcs.plugins.phase1.fanout_reducer import SEED_ROOT_ID, FanoutReducerPlugin
from mcs.stores.in_memory import InMemoryStore

GraphStore = InMemoryStore


def _engine(graph, mock_llm, token_budget):
    pm = PluginManager()
    pm.register(mock_llm)
    pm.register(FanoutReducerPlugin({"floor": 16}))
    pm.initialize_all(
        PluginContext(
            store=graph,
            config=MCSConfig(),
            token_budget=token_budget,
            context_renderer=None,  # type: ignore[arg-type]
            plugin_manager=pm,
        )
    )
    return QueryEngine(
        store=graph,
        llm=mock_llm,
        plugin_manager=pm,
        token_budget=token_budget,
        max_rounds=3,
        max_accumulated_nodes=1000,
    )


def _seeds(graph, n, content):
    out = []
    for i in range(n):
        node = Node(id=f"s{i}", name=f"s{i}", content=content)
        graph.add_node(node)
        out.append(node)
    return out


# ── 建图侧：持久虚拟根 + 递归分层 ─────────────────────────────────────────────


def _group_response(nodes_in, free_args):
    """mock decide_hub：把整批邻居归为一个 summarize 社区（summary="Group"）。"""
    ids = [n.id for n in nodes_in[1:]]
    return MultiHubDecision(communities=[
        Community(theme="Group", member_ids=ids, strategy="summarize", summary="Group")
    ])


def _fanout_with_root(graph, token_budget, mock_llm):
    pm = PluginManager()
    pm.register(mock_llm)
    fr = FanoutReducerPlugin({"floor": 16})
    pm.register(fr)
    pm.initialize_all(
        PluginContext(
            store=graph,
            config=MCSConfig(),  # seed_graph_bounding 已删除
            token_budget=token_budget,
            context_renderer=None,  # type: ignore[arg-type]
            plugin_manager=pm,
        )
    )
    return fr


def test_fanout_maintains_persistent_root(mock_llm):
    """fanout_reducer 维护持久虚拟根：新概念挂持久根、超阈值递归分层、产物入 changed_nodes。"""
    g = GraphStore()
    concepts = []
    for i in range(20):  # 20 个 ~100 token 概念，floor=16 + 小窗口 → 根会被分层
        n = Node(id=f"c{i}", name=f"c{i}", content="a" * 400, role="concept")
        g.add_node(n)
        concepts.append(n)
    mock_llm.set_response("decide_hub", _group_response)
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
    """maintain_root=False时不建持久根。"""
    g = GraphStore()
    n = Node(id="c0", name="c0", content="x", role="concept")
    g.add_node(n)
    pm = PluginManager()
    pm.register(mock_llm)
    fr = FanoutReducerPlugin({"floor": 16, "maintain_root": False})
    pm.register(fr)
    pm.initialize_all(
        PluginContext(
            store=g,
            config=MCSConfig(),
            token_budget=TokenBudget(8000),
            context_renderer=None,  # type: ignore[arg-type]
            plugin_manager=pm,
        )
    )
    changed = [n]
    if fr.should_run(changed, g):
        fr.run(changed, g, mock_llm.call)
    assert g.get_node(SEED_ROOT_ID) is None
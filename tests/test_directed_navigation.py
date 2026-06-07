"""方向感知导航测试：_navigate 仅沿 out 边下钻、不沿语义/上行边回退、无环。

覆盖 seed-graph-directional-hierarchy 任务 3.2 / 3.3。
"""

from __future__ import annotations

from mcs.core.config import MCSConfig
from mcs.core.graph import Node
from mcs.core.plugin_manager import PluginContext, PluginManager
from mcs.core.token_budget import TokenBudget
from mcs.plugins.phase1.fanout_reducer import SEED_ROOT_ID
from mcs.plugins.phase1.hub_fallback import HubFallbackEntryPlugin
from mcs.stores.in_memory import InMemoryStore

GraphStore = InMemoryStore


def _init_plugin(plugin, graph, *extra_plugins):
    pm = PluginManager()
    for p in extra_plugins:
        pm.register(p)
    pm.register(plugin)
    ctx = PluginContext(
        store=graph,
        config=MCSConfig(),
        token_budget=TokenBudget(8000),
        context_renderer=None,  # type: ignore[arg-type]
        plugin_manager=pm,
    )
    pm.initialize_all(ctx)
    return plugin


def test_navigate_only_follows_out_edges(mock_llm):
    """_navigate 只沿 out 边下钻，不沿 bidirectional 边回退。"""
    g = GraphStore()
    root = Node(id=SEED_ROOT_ID, name="__seed_root__", content="", role="hub")
    hub_a = Node(id="hub_a", name="Hub A", content="desc A", role="hub")
    leaf_b = Node(id="leaf_b", name="Leaf B", content="content B")
    semantic_c = Node(id="semantic_c", name="Semantic C", content="peer")

    for n in [root, hub_a, leaf_b, semantic_c]:
        g.add_node(n)

    # 层级边（out）：root→hub_a→leaf_b
    g.add_edge(SEED_ROOT_ID, "hub_a", direction="out")
    g.add_edge("hub_a", "leaf_b", direction="out")
    # 语义边（bidirectional）：hub_a↔semantic_c
    g.add_edge("hub_a", "semantic_c", direction="bidirectional")

    plugin = HubFallbackEntryPlugin()
    _init_plugin(plugin, g, mock_llm)

    # LLM 总是返回第一个候选
    def _route(nodes_in, _free_args):
        candidates = nodes_in[1:] if len(nodes_in) > 1 else []
        return [candidates[0].id] if candidates else []

    mock_llm.set_response("navigate_hub", _route)

    seeds = plugin.locate("query", None)

    # 应该能沿 out 边下钻到 leaf_b
    seed_ids = {n.id for n in seeds}
    assert "leaf_b" in seed_ids
    # semantic_c 是 bidirectional 边，不应出现在导航路径中
    assert "semantic_c" not in seed_ids


def test_navigate_does_not_come_back_via_uplink(mock_llm):
    """有向拓扑下，下钻不沿上行边（member→old_parent）回退到祖先。"""
    g = GraphStore()
    root = Node(id=SEED_ROOT_ID, name="__seed_root__", content="", role="hub")
    a = Node(id="a", name="A", content="parent", role="hub")
    b = Node(id="b", name="B", content="member")

    for n in [root, a, b]:
        g.add_node(n)

    # 下行边：root→a, a→b
    g.add_edge(SEED_ROOT_ID, "a", direction="out")
    g.add_edge("a", "b", direction="out")
    # 上行边：b→a（成员回指原父）
    g.add_edge("b", "a", direction="out")

    plugin = HubFallbackEntryPlugin()
    _init_plugin(plugin, g, mock_llm)

    # 记录所有 LLM 调用中的候选节点
    all_candidates = []
    def _track(nodes_in, _free_args):
        candidates = nodes_in[1:] if len(nodes_in) > 1 else []
        all_candidates.extend([n.id for n in candidates])
        return [candidates[0].id] if candidates else []

    mock_llm.set_response("navigate_hub", _track)

    seeds = plugin.locate("query", None)

    # 验证：所有候选节点只出现一次（无环）
    from collections import Counter
    counts = Counter(all_candidates)
    for nid, count in counts.items():
        assert count == 1, f"Candidate {nid} appeared {count} times - cycle detected"

    # 最终种子应该包含 b（下钻成功）
    assert "b" in {n.id for n in seeds}


def test_navigate_from_root_does_not_revisit_ancestors(mock_llm):
    """从持久根下钻时，祖先/旁系不会通过上行边重新纳入候选。"""
    g = GraphStore()
    root = Node(id=SEED_ROOT_ID, name="__seed_root__", content="", role="hub")
    hub1 = Node(id="hub1", name="Hub1", content="hub 1", role="hub")
    hub2 = Node(id="hub2", name="Hub2", content="hub 2", role="hub")
    leaf1 = Node(id="leaf1", name="Leaf1", content="leaf under hub1")
    leaf2 = Node(id="leaf2", name="Leaf2", content="leaf under hub2")

    for n in [root, hub1, hub2, leaf1, leaf2]:
        g.add_node(n)

    # 层级结构：root → hub1, hub2；hub1 → leaf1；hub2 → leaf2
    g.add_edge(SEED_ROOT_ID, "hub1", direction="out")
    g.add_edge(SEED_ROOT_ID, "hub2", direction="out")
    g.add_edge("hub1", "leaf1", direction="out")
    g.add_edge("hub2", "leaf2", direction="out")
    # 上行边：leaf→hub
    g.add_edge("leaf1", "hub1", direction="out")
    g.add_edge("leaf2", "hub2", direction="out")

    plugin = HubFallbackEntryPlugin()
    _init_plugin(plugin, g, mock_llm)

    # 选择 hub1 下钻，然后选择 leaf1
    routes = {
        SEED_ROOT_ID: ["hub1"],
        "hub1": ["leaf1"],
    }
    def _route(nodes_in, _free_args):
        first = nodes_in[0] if nodes_in else None
        return routes.get(first.id, []) if first else []

    mock_llm.set_response("navigate_hub", _route)

    seeds = plugin.locate("query", None)

    # 应该下钻到 leaf1，而不是回退到 root 或 hub2
    seed_ids = {n.id for n in seeds}
    assert "leaf1" in seed_ids
    assert SEED_ROOT_ID not in seed_ids  # 根不应作为种子


def test_whole_circle_marked_visited(mock_llm):
    """每层整圈候选入 visited，后续层不会重复检视。"""
    g = GraphStore()
    root = Node(id=SEED_ROOT_ID, name="__seed_root__", content="", role="hub")
    c1 = Node(id="c1", name="C1", content="child 1")
    c2 = Node(id="c2", name="C2", content="child 2")
    c3 = Node(id="c3", name="C3", content="child 3")

    for n in [root, c1, c2, c3]:
        g.add_node(n)
    g.add_edge(SEED_ROOT_ID, "c1", direction="out")
    g.add_edge(SEED_ROOT_ID, "c2", direction="out")
    g.add_edge(SEED_ROOT_ID, "c3", direction="out")

    plugin = HubFallbackEntryPlugin()
    _init_plugin(plugin, g, mock_llm)

    # 记录所有 LLM 调用
    all_calls = []
    def _track(nodes_in, _free_args):
        all_calls.append([n.id for n in nodes_in])
        return [nodes_in[1].id] if len(nodes_in) > 1 else []  # 选第一个候选

    mock_llm.set_response("navigate_hub", _track)

    plugin.locate("query", None)

    # 验证：所有候选（c1, c2, c3）只出现一次
    candidate_appearances = {}
    for call in all_calls:
        for nid in call[1:]:  # 跳过 frontier 节点
            candidate_appearances[nid] = candidate_appearances.get(nid, 0) + 1

    for nid, count in candidate_appearances.items():
        assert count == 1, f"Candidate {nid} appeared {count} times, expected 1"
"""HubFallbackEntryPlugin 测试：navigate_hub LLM 导航 + 优雅降级。"""

from __future__ import annotations

from mcs.core.graph import Node
from mcs.core.plugin_manager import PluginContext, PluginManager
from mcs.core.token_budget import TokenBudget
from mcs.plugins.phase1.hub_fallback import HubFallbackEntryPlugin
from mcs.stores.in_memory import InMemoryStore

GraphStore = InMemoryStore


def _hub_graph() -> GraphStore:
    """根枢纽 h → {c1, c2}（c1 再挂一个 g1）。使用有向下行边构建层级。"""
    g = GraphStore()
    g.add_node(Node(id="h", name="根枢纽", content="顶层", role="hub"))
    g.add_node(Node(id="c1", name="子概念1", content="..."))
    g.add_node(Node(id="c2", name="子概念2", content="..."))
    g.add_node(Node(id="g1", name="孙概念1", content="..."))
    # 层级边使用 out 方向
    g.add_edge("h", "c1", direction="out")
    g.add_edge("h", "c2", direction="out")
    g.add_edge("c1", "g1", direction="out")
    return g


def _init(plugin: HubFallbackEntryPlugin, graph: GraphStore, *plugins) -> None:
    pm = PluginManager()
    for p in plugins:
        pm.register(p)
    pm.register(plugin)
    ctx = PluginContext(
        store=graph,
        config=None,  # type: ignore[arg-type]
        token_budget=TokenBudget(8000),
        context_renderer=None,  # type: ignore[arg-type]
        plugin_manager=pm,
    )
    pm.initialize_all(ctx)


def test_navigate_hub_called_and_drills(mock_llm):
    """有 hub 且配置 LLM 时，必须发起 navigate_hub 调用并按返回下钻。"""
    g = _hub_graph()
    plugin = HubFallbackEntryPlugin()
    _init(plugin, g, mock_llm)
    # 第一层 frontier=[h] 选 c1；第二层 frontier=[c1] 选 g1。用首个节点 id 路由。
    routes = {"h": ["c1"], "c1": ["g1"]}

    def _route(nodes_in, _free_args):
        first = (nodes_in or [None])[0]
        return routes.get(first.id, []) if first is not None else []

    mock_llm.set_response("navigate_hub", _route)
    seeds = plugin.locate("找孙概念", None)

    purposes = [c["purpose"] for c in mock_llm.call_log]
    assert "navigate_hub" in purposes
    seed_ids = {n.id for n in seeds}
    assert "g1" in seed_ids  # 成功下钻两层


def test_no_hubs_returns_empty(mock_llm):
    """图中没有 hub 角色节点时返回空，不发起 LLM 调用。"""
    g = GraphStore()
    g.add_node(Node(id="x", name="普通", content="", role="concept"))
    plugin = HubFallbackEntryPlugin()
    _init(plugin, g, mock_llm)
    assert plugin.locate("q", None) == []
    assert mock_llm.call_log == []


def test_graceful_fallback_without_llm():
    """未配置 LLM 时优雅降级：直接返回 hub 集合作为种子。"""
    g = _hub_graph()
    plugin = HubFallbackEntryPlugin()
    _init(plugin, g)  # 不注册任何 LLM
    seeds = plugin.locate("q", None)
    assert {n.id for n in seeds} == {"h"}


def test_disable_llm_navigation_returns_hubs(mock_llm):
    """use_llm_navigation=False 时即便有 LLM 也只返回 hub 集合。"""
    g = _hub_graph()
    plugin = HubFallbackEntryPlugin({"use_llm_navigation": False})
    _init(plugin, g, mock_llm)
    seeds = plugin.locate("q", None)
    assert {n.id for n in seeds} == {"h"}
    assert mock_llm.call_log == []


def test_navigates_from_persistent_root(mock_llm):
    """存在持久根 __seed_root__ 时，从根自顶向下导航；绝不把合成根当种子。"""
    from mcs.plugins.phase1.fanout_reducer import SEED_ROOT_ID

    g = GraphStore()
    g.add_node(Node(id=SEED_ROOT_ID, name="__seed_root__", content="", role="hub"))
    g.add_node(Node(id="t1", name="顶层1", content="..."))
    g.add_node(Node(id="t2", name="顶层2", content="..."))
    g.add_node(Node(id="leaf", name="叶", content="..."))
    # 层级边使用 out 方向
    g.add_edge(SEED_ROOT_ID, "t1", direction="out")
    g.add_edge(SEED_ROOT_ID, "t2", direction="out")
    g.add_edge("t1", "leaf", direction="out")
    plugin = HubFallbackEntryPlugin()
    _init(plugin, g, mock_llm)
    routes = {SEED_ROOT_ID: ["t1"], "t1": ["leaf"]}

    def _route(nodes_in, _free_args):
        first = (nodes_in or [None])[0]
        return routes.get(first.id, []) if first is not None else []

    mock_llm.set_response("navigate_hub", _route)
    seeds = plugin.locate("找叶", None)

    seed_ids = {n.id for n in seeds}
    assert SEED_ROOT_ID not in seed_ids  # 绝不返回合成根
    assert "leaf" in seed_ids            # 从根下钻到叶


def test_root_present_no_llm_returns_children(mock_llm):
    """有持久根但关闭导航：返回根的直接子节点作种子（不含根本身）。"""
    from mcs.plugins.phase1.fanout_reducer import SEED_ROOT_ID

    g = GraphStore()
    g.add_node(Node(id=SEED_ROOT_ID, name="__seed_root__", content="", role="hub"))
    g.add_node(Node(id="t1", name="顶层1", content="..."))
    g.add_node(Node(id="t2", name="顶层2", content="..."))
    # 层级边使用 out 方向
    g.add_edge(SEED_ROOT_ID, "t1", direction="out")
    g.add_edge(SEED_ROOT_ID, "t2", direction="out")
    plugin = HubFallbackEntryPlugin({"use_llm_navigation": False})
    _init(plugin, g, mock_llm)
    seeds = plugin.locate("q", None)
    # 根的 out 邻居是 t1, t2
    assert {n.id for n in seeds} == {"t1", "t2"}

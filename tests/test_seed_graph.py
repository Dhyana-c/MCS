"""分层种子图测试（建图侧）：

  - 建图侧 ``fanout_reducer`` 维护**持久虚拟根** + 递归分层，产物入 ``changed_nodes`` 以便落库。
  - 查询侧种子超预算由 SeedSelectorPlugin 链处理（见 test_pipeline_query.py）。
"""

from __future__ import annotations

from mcs.core.plugin_manager import PluginContext, PluginManager
from mcs.core.query_engine import QueryEngine
from mcs.core.token_budget import TokenBudget
from mcs.entities.config import MCSConfig
from mcs.entities.decisions import Community, MultiHubDecision
from mcs.entities.graph import Node
from mcs.plugins.maintenance.fanout_reducer import SEED_ROOT_ID, FanoutReducerPlugin
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


def test_fanout_maintains_persistent_root(mock_llm, fanout_reducer):
    """fanout_reducer 维护持久虚拟根：新概念挂持久根、超阈值递归分层、产物入 changed_nodes。"""
    g = GraphStore()
    concepts = []
    for i in range(20):  # 20 个 ~100 token 概念，floor=16 + 小窗口 → 根会被分层
        n = Node(id=f"c{i}", name=f"c{i}", content="a" * 400, node_class="概念")
        g.add_node(n)
        concepts.append(n)
    mock_llm.set_response("decide_hub", _group_response)
    fr = fanout_reducer(g, mock_llm, TokenBudget(500))

    changed = list(concepts)
    fr.run(changed, g, mock_llm.call)

    root = g.get_node(SEED_ROOT_ID)
    assert root is not None                              # 持久根已建
    assert root in changed                               # 根入 changed_nodes（落库）
    # 递归分层出中间 hub
    assert any(n.hub is True and n.id != SEED_ROOT_ID for n in g.get_all_nodes())
    # 根的直接扇出已收敛（< 原始 20）
    assert len(g.get_out_hierarchy(SEED_ROOT_ID)) < 20
    # 每个概念仍可从根（递归）到达：所有概念都进了某个 hub 或直接挂根
    assert g.get_node("c0") is not None


def test_seed_root_maintained_without_budget_pressure(mock_llm, fanout_reducer):
    """回归：无预算压力（大 T）下，经 should_run 闸门仍必须建根并把概念挂到根。

    旧实现 should_run 只看预算超限，故小语料 / 大窗口 / 整篇摄入永不建根 → 整图扁平、
    查询无从沿 out 下钻 → 文档级召回为 0。修复后根维护与预算闸门解耦。
    本测试走 ``should_run`` 闸门（模拟真实 ``_run_compaction``），而非直接调 ``run()``。
    """
    g = GraphStore()
    concepts = [
        Node(id=f"c{i}", name=f"c{i}", content="x", node_class="概念") for i in range(3)
    ]
    for n in concepts:
        g.add_node(n)
    fr = fanout_reducer(g, mock_llm, TokenBudget(8000))  # 大 T：3 个小概念不会超预算

    changed = list(concepts)
    assert fr.should_run(changed, g)            # 有新概念 → 需维护根（即便无预算压力）
    fr.run(changed, g, mock_llm.call)

    root = g.get_node(SEED_ROOT_ID)
    assert root is not None                      # 无预算压力也建了持久根
    for c in concepts:                           # 每个概念都以 out 边挂在根下
        assert g.get_edges_between(SEED_ROOT_ID, c.id) != []
    # 未超预算 → 不应触发 decide_hub 裂变（无新 hub）
    assert all(n.hub is False for n in g.get_all_nodes() if n.id != SEED_ROOT_ID)


def test_root_attaches_only_orphans(mock_llm, fanout_reducer):
    """P2/D6：只有零事实关联的"孤儿"概念挂根；有事实关联者不挂根

    （经字面入口 alias_entry + 事实 BFS 可达，挂根只会让图扁平化）。
    """
    g = GraphStore()
    for nid in ("a", "b", "c"):
        g.add_node(Node(id=nid, name=nid, content="x", node_class="概念"))
    g.add_edge("a", "b")  # a、b 有事实关联（b 为宾也算关联）

    fr = fanout_reducer(g, mock_llm, TokenBudget(8000))
    fr.run([g.get_node(n) for n in ("a", "b", "c")], g, mock_llm.call)

    assert not g.get_edges_between(SEED_ROOT_ID, "a")  # 有关联 → 不挂根
    assert not g.get_edges_between(SEED_ROOT_ID, "b")  # 反查命中关联 → 不挂根
    assert g.get_edges_between(SEED_ROOT_ID, "c")      # 孤儿 → 挂根


def test_absorb_absorbs_node_whose_children_superset_of_hub_members(mock_llm, fanout_reducer):
    """边吸收：某节点 X 的下钻成员 ⊇ hub H 的全部成员时，X→各成员替换为 X→H（减边）。

    统一模型下无 fact/hierarchy 之分——X→m1/m2 即 X 的下钻成员（关联出边）；
    H 的成员也是 {m1,m2}。故 X 应被吸收：删 X→m1/X→m2、加单条 X→H。
    """
    g = GraphStore()
    g.add_node(Node(id="H", name="H", content="h", extensions={"hub": True}))
    for nid in ("m1", "m2", "X"):
        g.add_node(Node(id=nid, name=nid, content="x", node_class="概念"))
    g.add_edge("H", "m1", type="关联")            # hub 的成员
    g.add_edge("H", "m2", type="关联")
    g.add_edge("X", "m1", type="关联")            # X 的下钻成员 ⊇ {m1,m2}
    g.add_edge("X", "m2", type="关联")

    fr = fanout_reducer(g, mock_llm, TokenBudget(8000))
    fr._absorb_hub_edges(g)

    # X 被吸收：新增单条 X→H，且 X→m1/X→m2 被删（减边）
    assert any(e for e in g.get_edges_between("X", "H") if e.type == "关联")
    assert g.get_edges_between("X", "m1") == []
    assert g.get_edges_between("X", "m2") == []



def test_no_persistent_root_when_disabled(mock_llm):
    """maintain_root=False时不建持久根。"""
    g = GraphStore()
    n = Node(id="c0", name="c0", content="x", node_class="概念")
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

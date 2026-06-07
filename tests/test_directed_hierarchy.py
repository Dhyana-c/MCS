"""层级边有向化测试：_reorganize 有向拓扑、_maintain_seed_root 有向下行、方向落库保真。

覆盖 seed-graph-directional-hierarchy 任务 2.2 / 2.4。
"""

from __future__ import annotations

import tempfile

from mcs.core.config import MCSConfig
from mcs.core.decisions import Community, MultiHubDecision
from mcs.core.graph import Node
from mcs.core.plugin_manager import PluginContext, PluginManager
from mcs.core.token_budget import TokenBudget
from mcs.plugins.phase1.fanout_reducer import SEED_ROOT_ID, FanoutReducerPlugin
from mcs.stores.in_memory import InMemoryStore
from mcs.stores.sqlite_store import SQLiteStore

GraphStore = InMemoryStore


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
            config=MCSConfig(seed_graph_bounding=True),
            token_budget=token_budget,
            context_renderer=None,  # type: ignore[arg-type]
            plugin_manager=pm,
        )
    )
    return fr


def test_reorganize_produces_directed_topology():
    """对 a↔b, a↔c 基于 {b,c} 提 hub d ⇒ a→d, d→b, d→c, b→a, c→a。

    验证：
    - 下行边 a→d, d→b, d→c 均为 direction="out"
    - 上行边 b→a, c→a 均为 direction="out"
    - 不存在双向的 a↔b 或 a↔c
    """
    g = GraphStore()
    a = Node(id="a", name="A", content="x" * 400)
    b = Node(id="b", name="B", content="x" * 400)
    c = Node(id="c", name="C", content="x" * 400)
    d = Node(id="d", name="Hub D", content="cluster", role="hub")
    for n in [a, b, c, d]:
        g.add_node(n)
    g.add_edge("a", "b", direction="bidirectional")
    g.add_edge("a", "c", direction="bidirectional")

    fr = FanoutReducerPlugin({"floor": 2})
    fr.token_budget = TokenBudget(500)
    fr._reorganize(a, d, [b, c], g)

    # 下行边 a→d
    edge_ad = g.get_edge("a", "d")
    assert edge_ad is not None
    assert edge_ad.direction == "out"
    assert edge_ad.source_id == "a"
    assert edge_ad.target_id == "d"

    # 下行边 d→b, d→c
    edge_db = g.get_edge("d", "b")
    assert edge_db is not None
    assert edge_db.direction == "out"
    assert edge_db.source_id == "d"

    edge_dc = g.get_edge("d", "c")
    assert edge_dc is not None
    assert edge_dc.direction == "out"
    assert edge_dc.source_id == "d"

    # 上行边 b→a, c→a
    edge_ba = g.get_edge("b", "a")
    assert edge_ba is not None
    assert edge_ba.direction == "out"
    assert edge_ba.source_id == "b"

    edge_ca = g.get_edge("c", "a")
    assert edge_ca is not None
    assert edge_ca.direction == "out"
    assert edge_ca.source_id == "c"

    # 不存在双向的 a↔b 或 a↔c
    assert g.get_edge("a", "b") is None or g.get_edge("a", "b").direction != "bidirectional"


def test_reorganize_out_neighbors_for_navigation():
    """有向拓扑下，a 的 out 邻居只有 d（不含 b/c），d 的 out 邻居有 b 和 c。"""
    g = GraphStore()
    a = Node(id="a", name="A", content="x" * 400)
    b = Node(id="b", name="B", content="x" * 400)
    c = Node(id="c", name="C", content="x" * 400)
    d = Node(id="d", name="Hub D", content="cluster", role="hub")
    for n in [a, b, c, d]:
        g.add_node(n)
    g.add_edge("a", "b", direction="bidirectional")
    g.add_edge("a", "c", direction="bidirectional")

    fr = FanoutReducerPlugin({"floor": 2})
    fr.token_budget = TokenBudget(500)
    fr._reorganize(a, d, [b, c], g)

    # a 的 out 邻居：只有 d
    assert {n.id for n in g.get_out_neighbors("a")} == {"d"}
    # d 的 out 邻居：b 和 c
    assert {n.id for n in g.get_out_neighbors("d")} == {"b", "c"}
    # b 的 out 邻居：只有 a（上行回指）
    assert {n.id for n in g.get_out_neighbors("b")} == {"a"}


def test_maintain_seed_root_uses_out_edges(mock_llm):
    """_maintain_seed_root 把新概念挂根用有向下行 root→concept（out）。"""
    g = GraphStore()
    concepts = []
    for i in range(20):
        n = Node(id=f"c{i}", name=f"c{i}", content="a" * 400, role="concept")
        g.add_node(n)
        concepts.append(n)
    mock_llm.set_response("decide_hub", _group_response)
    fr = _fanout_with_root(g, TokenBudget(500), mock_llm)

    changed = list(concepts)
    fr.run(changed, g, mock_llm.call)

    root = g.get_node(SEED_ROOT_ID)
    assert root is not None

    # 根到直接子节点的边应为 out 方向
    for edge in g.get_all_edges():
        if edge.source_id == SEED_ROOT_ID:
            assert edge.direction == "out", (
                f"root→{edge.target_id} should be out, got {edge.direction}"
            )


def test_directed_hierarchy_persisted_via_save_full(mock_llm):
    """有向层级产物经 save_full 落库后方向保真。"""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    storage = SQLiteStore({"path": db_path})
    storage.initialize()
    concepts = []
    for i in range(20):
        n = Node(id=f"c{i}", name=f"c{i}", content="a" * 400, role="concept")
        storage.add_node(n)
        concepts.append(n)
    mock_llm.set_response("decide_hub", _group_response)
    fr = _fanout_with_root(storage, TokenBudget(500), mock_llm)
    changed = list(concepts)
    fr.run(changed, storage, mock_llm.call)

    # 保存
    storage.save_full()

    # 加载并验证方向
    loaded = SQLiteStore({"path": db_path})
    loaded.initialize()
    loaded.load()
    for edge in loaded.get_all_edges():
        if edge.source_id == SEED_ROOT_ID:
            assert edge.direction == "out"

    # 验证 out 邻居视图在加载后仍正确
    root = loaded.get_node(SEED_ROOT_ID)
    assert root is not None
    out_nb = {n.id for n in loaded.get_out_neighbors(SEED_ROOT_ID)}
    all_nb = {n.id for n in loaded.get_neighbors(SEED_ROOT_ID)}
    # out 邻居是全部邻居的子集
    assert out_nb.issubset(all_nb)

    storage.shutdown()
    loaded.shutdown()
    import os
    os.unlink(db_path)


def test_semantic_edges_remain_bidirectional_after_reorganize():
    """_reorganize 不影响语义边（bidirectional）。"""
    g = GraphStore()
    a = Node(id="a", name="A", content="x" * 400)
    b = Node(id="b", name="B", content="x" * 400)
    c = Node(id="c", name="C", content="x" * 400)
    x = Node(id="x", name="X", content="semantic peer")
    d = Node(id="d", name="Hub D", content="cluster", role="hub")
    for n in [a, b, c, x, d]:
        g.add_node(n)
    g.add_edge("a", "b", direction="bidirectional")
    g.add_edge("a", "c", direction="bidirectional")
    g.add_edge("a", "x", direction="bidirectional")  # 语义边，不在 members 中

    fr = FanoutReducerPlugin({"floor": 2})
    fr.token_budget = TokenBudget(500)
    fr._reorganize(a, d, [b, c], g)

    # a↔x 语义边仍为 bidirectional
    edge_ax = g.get_edge("a", "x")
    assert edge_ax is not None
    assert edge_ax.direction == "bidirectional"

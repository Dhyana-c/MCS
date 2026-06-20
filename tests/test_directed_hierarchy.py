"""单向边层级拓扑测试：_reorganize 纯下行、_maintain_seed_root 单向、落库保真。

覆盖单向边模型下的层级重组、导航邻居、根维护、持久化、语义边保留。
"""

from __future__ import annotations

import os
import tempfile

from mcs.core.token_budget import TokenBudget
from mcs.entities.decisions import Community, MultiHubDecision
from mcs.entities.graph import Node
from mcs.plugins.maintenance.fanout_reducer import SEED_ROOT_ID, FanoutReducerPlugin
from mcs.stores.in_memory import InMemoryStore
from mcs.stores.sqlite_store import SQLiteStore

GraphStore = InMemoryStore


def _group_response(nodes_in, free_args):
    """mock decide_hub：把整批邻居归为一个 summarize 社区（summary="Group"）。"""
    ids = [n.id for n in nodes_in[1:]]
    return MultiHubDecision(communities=[
        Community(theme="Group", member_ids=ids, strategy="summarize", summary="Group")
    ])


def test_reorganize_produces_pure_downstream_topology():
    """_reorganize(a, d, [b,c], g) 纯下行：删 a→b, a→c；建 a→d, d→b, d→c。

    无上行边：b→a 和 c→a 不存在。
    """
    g = GraphStore()
    a = Node(id="a", name="A", content="x" * 400)
    b = Node(id="b", name="B", content="x" * 400)
    c = Node(id="c", name="C", content="x" * 400)
    d = Node(id="d", name="Hub D", content="cluster", extensions={"hub": True})
    for n in [a, b, c, d]:
        g.add_node(n)
    g.add_edge("a", "b")
    g.add_edge("a", "c")

    fr = FanoutReducerPlugin({"floor": 2})
    fr.token_budget = TokenBudget(500)
    fr._reorganize(a, d, [b, c], g)

    # 下行边 a→d
    edges_ad = g.get_edges_between("a", "d")
    assert len(edges_ad) == 1
    edge_ad = edges_ad[0]
    assert edge_ad.source_id == "a"
    assert edge_ad.target_id == "d"

    # 下行边 d→b
    edges_db = g.get_edges_between("d", "b")
    assert len(edges_db) == 1
    edge_db = edges_db[0]
    assert edge_db.source_id == "d"
    assert edge_db.target_id == "b"

    # 下行边 d→c
    edges_dc = g.get_edges_between("d", "c")
    assert len(edges_dc) == 1
    edge_dc = edges_dc[0]
    assert edge_dc.source_id == "d"
    assert edge_dc.target_id == "c"

    # 原始直连边 a→b, a→c 已删除
    assert g.get_edges_between("a", "b") == []
    assert g.get_edges_between("a", "c") == []

    # 无上行边 b→a, c→a
    assert g.get_edges_between("b", "a") == []
    assert g.get_edges_between("c", "a") == []


def test_reorganize_out_neighbors():
    """重组后导航邻居：a 的邻居只有 d，d 的邻居有 b/c，b 的邻居为空（无上行）。"""
    g = GraphStore()
    a = Node(id="a", name="A", content="x" * 400)
    b = Node(id="b", name="B", content="x" * 400)
    c = Node(id="c", name="C", content="x" * 400)
    d = Node(id="d", name="Hub D", content="cluster", extensions={"hub": True})
    for n in [a, b, c, d]:
        g.add_node(n)
    g.add_edge("a", "b")
    g.add_edge("a", "c")

    fr = FanoutReducerPlugin({"floor": 2})
    fr.token_budget = TokenBudget(500)
    fr._reorganize(a, d, [b, c], g)

    # a 的邻居：只有 d
    assert {n.id for n in g.get_out_hierarchy("a")} == {"d"}
    # d 的邻居：b 和 c
    assert {n.id for n in g.get_out_hierarchy("d")} == {"b", "c"}
    # b 的邻居：空（无上行回指）
    assert {n.id for n in g.get_out_hierarchy("b")} == set()
    # c 的邻居：空（无上行回指）
    assert {n.id for n in g.get_out_hierarchy("c")} == set()


def test_maintain_seed_root_uses_unidirectional_edges(mock_llm, fanout_reducer):
    """root→concept 边是单向的：get_neighbors(root) 含概念，get_neighbors(concept) 不含 root。"""
    g = GraphStore()
    concepts = []
    for i in range(20):
        n = Node(id=f"c{i}", name=f"c{i}", content="a" * 400, node_class="概念")
        g.add_node(n)
        concepts.append(n)
    mock_llm.set_response("decide_hub", _group_response)
    fr = fanout_reducer(g, mock_llm, TokenBudget(500))

    changed = list(concepts)
    fr.run(changed, g, mock_llm.call)

    root = g.get_node(SEED_ROOT_ID)
    assert root is not None

    # get_neighbors(root) 应包含概念节点
    root_neighbors = {n.id for n in g.get_out_hierarchy(SEED_ROOT_ID)}
    assert len(root_neighbors) > 0

    # 反方向：get_neighbors(任意概念) 不含 root（单向 root→concept）
    for concept in concepts:
        concept_neighbors = {n.id for n in g.get_out_hierarchy(concept.id)}
        assert SEED_ROOT_ID not in concept_neighbors, (
            f"概念 {concept.id} 的邻居不应包含 root，但发现 {concept_neighbors}"
        )

    # root→concept 边的 source_id == root，target_id == concept
    for edge in g.get_all_edges():
        if edge.source_id == SEED_ROOT_ID:
            assert edge.target_id != SEED_ROOT_ID
            # Edge 不再有 direction 字段
            assert not hasattr(edge, "direction") or getattr(edge, "direction", None) is None


def test_hierarchy_persisted_via_save_full(mock_llm, fanout_reducer):
    """单向层级产物经 save_full 落库后边保真（source_id / target_id 正确）。"""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = f.name

    storage = SQLiteStore({"path": db_path})
    storage.initialize()
    concepts = []
    for i in range(20):
        n = Node(id=f"c{i}", name=f"c{i}", content="a" * 400, node_class="概念")
        storage.add_node(n)
        concepts.append(n)
    mock_llm.set_response("decide_hub", _group_response)
    fr = fanout_reducer(storage, mock_llm, TokenBudget(500))
    changed = list(concepts)
    fr.run(changed, storage, mock_llm.call)

    # 保存
    storage.save_full()

    # 加载并验证单向边
    loaded = SQLiteStore({"path": db_path})
    loaded.initialize()
    loaded.load()

    # 加载后 root 存在
    root = loaded.get_node(SEED_ROOT_ID)
    assert root is not None

    # 验证 root→concept 边保真
    for edge in loaded.get_all_edges():
        if edge.source_id == SEED_ROOT_ID:
            # Edge 只有 source_id / target_id，无 direction
            assert edge.target_id is not None

    # 验证 get_neighbors 加载后仍正确（单向：root→concept 成立，concept→root 不成立）
    root_neighbors = {n.id for n in loaded.get_out_hierarchy(SEED_ROOT_ID)}
    assert len(root_neighbors) > 0
    for cid in [f"c{i}" for i in range(20)]:
        node = loaded.get_node(cid)
        if node is not None:
            concept_neighbors = {n.id for n in loaded.get_out_hierarchy(cid)}
            assert SEED_ROOT_ID not in concept_neighbors

    storage.shutdown()
    loaded.shutdown()
    os.unlink(db_path)


def test_semantic_edges_unaffected_by_reorganize():
    """_reorganize 不影响未涉及的边（不在 members 中的边原样保留）。"""
    g = GraphStore()
    a = Node(id="a", name="A", content="x" * 400)
    b = Node(id="b", name="B", content="x" * 400)
    c = Node(id="c", name="C", content="x" * 400)
    x = Node(id="x", name="X", content="semantic peer")
    d = Node(id="d", name="Hub D", content="cluster", extensions={"hub": True})
    for n in [a, b, c, x, d]:
        g.add_node(n)
    g.add_edge("a", "b")
    g.add_edge("a", "c")
    g.add_edge("a", "x")  # 语义边，不在 members 中

    fr = FanoutReducerPlugin({"floor": 2})
    fr.token_budget = TokenBudget(500)
    fr._reorganize(a, d, [b, c], g)

    # a→x 边原样保留
    edges_ax = g.get_edges_between("a", "x")
    assert len(edges_ax) == 1
    edge_ax = edges_ax[0]
    assert edge_ax.source_id == "a"
    assert edge_ax.target_id == "x"

    # 确认被重组的边已正确变更
    assert g.get_edges_between("a", "d") != []
    assert g.get_edges_between("d", "b") != []
    assert g.get_edges_between("d", "c") != []
    assert g.get_edges_between("a", "b") == []
    assert g.get_edges_between("a", "c") == []

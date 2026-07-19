"""``QueryEngine._traverse`` 图遍历原语测试（lightweight-query capability）。

读查询编排（``query()``）退役后，``_traverse`` 作为写管线关联定位 + agent 导航复用的
图遍历原语保留（见 openspec change ``retire-framework-query-pipeline``）。本文件**直接**
调 ``engine._traverse(...)``（不经已删除的 ``query()``），覆盖存活机制：

- BFS + ``visited`` 防环
- 安全阀（``max_rounds`` / ``max_accumulated_nodes``）
- 双角色路由（frontier / accumulated 解耦、结果/探索/两者、未选中不入 visited）
- read-repair 同名合并

select 输出经 MockLLM callable 注入（按节点 id 选编号），与 view_nodes 结构解耦。
"""

from __future__ import annotations

from conftest import make_query_engine

from mcs.core.query_engine import QueryContext
from mcs.entities.graph import Node
from mcs.stores.in_memory import InMemoryStore


def _select(result_ids=(), frontier_ids=()):
    """callable：从 view_nodes 按 id 选编号、分 result/frontier 两角色。"""
    def _fn(nodes_in, _free_args):
        idx = {n.id: i for i, n in enumerate(nodes_in, 1) if n is not None}
        return {
            "result": [idx[i] for i in result_ids if i in idx],
            "frontier": [idx[i] for i in frontier_ids if i in idx],
        }
    return _fn


def _cycle_graph():
    """A —关联— B —关联— C —关联— A（环）。"""
    g = InMemoryStore()
    for nid in ("a", "b", "c"):
        g.add_node(Node(id=nid, name=nid, content=nid))
    g.add_edge("a", "b")
    g.add_edge("b", "c")
    g.add_edge("c", "a")
    return g


# === BFS + visited ===


def test_traverse_empty_seeds_returns_empty(seeded_graph, mock_llm):
    engine = make_query_engine(seeded_graph, mock_llm)
    accumulated, edges = engine._traverse([], "x", QueryContext())
    assert accumulated == []
    assert edges == []


def test_traverse_bfs_cycle_terminates(mock_llm):
    """有环图 A→B→C→A：visited 防死循环，三节点各处理至多一次、全部到达。"""
    g = _cycle_graph()
    mock_llm.set_response("select_facts", _select(["a", "b", "c"], ["a", "b", "c"]))
    engine = make_query_engine(g, mock_llm)
    accumulated, _ = engine._traverse([g.get_node("a")], "cycle", QueryContext())
    assert {n.id for n in accumulated} == {"a", "b", "c"}  # 全到达、无重复


# === 安全阀 ===


def test_traverse_max_rounds_caps_depth(seeded_graph, mock_llm):
    """max_rounds=1：首轮（dl → nn）后终止，nn 的下钻 cnn 不可达。

    seeded_graph: dl — nn — cnn（cnn 在 nn 下钻侧）。首轮 dl 的视图暴露 dl/nn/ml，
    选 dl+nn 为 result；max_rounds=1 使第 2 轮（nn→cnn）不执行 → cnn 不进 accumulated。
    """
    mock_llm.set_response("select_facts", _select(["dl", "nn"], ["nn"]))
    engine = make_query_engine(seeded_graph, mock_llm, max_rounds=1)
    accumulated, _ = engine._traverse([seeded_graph.get_node("dl")], "x", QueryContext())
    ids = {n.id for n in accumulated}
    assert "cnn" not in ids  # 深度截断：cnn（2 跳外）未被扩展


def test_traverse_max_accumulated_nodes_caps(mock_llm):
    """max_accumulated_nodes=1：accumulated 达 1 即终止。"""
    g = _cycle_graph()
    mock_llm.set_response("select_facts", _select(["a", "b", "c"], ["a", "b", "c"]))
    engine = make_query_engine(g, mock_llm, max_accumulated_nodes=1)
    accumulated, _ = engine._traverse([g.get_node("a")], "x", QueryContext())
    assert len(accumulated) <= 1


# === 双角色路由（frontier / accumulated 解耦）===


def test_traverse_result_role_to_accumulated(seeded_graph, mock_llm):
    """标 `结果` 的节点进 accumulated（返回集）。"""
    mock_llm.set_response("select_facts", _select(["dl"]))
    engine = make_query_engine(seeded_graph, mock_llm, max_rounds=1)
    accumulated, _ = engine._traverse([seeded_graph.get_node("dl")], "x", QueryContext())
    assert {n.id for n in accumulated} == {"dl"}


def test_traverse_explore_role_not_in_return(seeded_graph, mock_llm):
    """仅标 `探索`（frontier）的节点 MUST NOT 进返回集（accumulated）。"""
    mock_llm.set_response("select_facts", _select([], ["dl"]))
    engine = make_query_engine(seeded_graph, mock_llm, max_rounds=2)
    accumulated, _ = engine._traverse([seeded_graph.get_node("dl")], "x", QueryContext())
    assert accumulated == []  # dl 仅探索、未进 accumulated


def test_traverse_seed_not_selected_returns_empty(seeded_graph, mock_llm):
    """种子未被任何角色选中 → accumulated 为空。"""
    mock_llm.set_response("select_facts", {"result": [], "frontier": []})
    engine = make_query_engine(seeded_graph, mock_llm, max_rounds=2)
    accumulated, _ = engine._traverse([seeded_graph.get_node("dl")], "x", QueryContext())
    assert accumulated == []


def test_traverse_both_roles_in_accumulated(seeded_graph, mock_llm):
    """同时标 `结果`+`探索`（两者）→ 进 accumulated（且随 frontier，但返回集只看 accumulated）。"""
    mock_llm.set_response("select_facts", _select(["dl"], ["dl"]))
    engine = make_query_engine(seeded_graph, mock_llm, max_rounds=1)
    accumulated, _ = engine._traverse([seeded_graph.get_node("dl")], "x", QueryContext())
    assert {n.id for n in accumulated} == {"dl"}


# === read-repair（同名合并）===


def test_traverse_read_repair_merges_same_name(mock_llm):
    """同 (name, universe) 的两节点经关联边相邻时：read-repair 把后遇者合并入先到者。

    x1 —关联— x2，同名"同义"、同 universe。select 把二者都标 result：x1（先到、种子）
    入 accumulated；x2 同名 → _try_read_repair 合并到 x1（不重复进 accumulated、并入别名/content）。
    """
    g = InMemoryStore()
    g.add_node(Node(id="x1", name="同义", content="内容A", universe="__reality__"))
    g.add_node(Node(id="x2", name="同义", content="内容B", universe="__reality__"))
    g.add_edge("x1", "x2")
    mock_llm.set_response("select_facts", _select(["x1", "x2"], []))
    engine = make_query_engine(g, mock_llm, max_rounds=1)
    accumulated, _ = engine._traverse([g.get_node("x1")], "x", QueryContext())
    ids = [n.id for n in accumulated]
    assert "x1" in ids
    assert "x2" not in ids  # x2 并入 x1（read-repair）

"""separate-accumulate-frontier：双角色解耦 + frontier 安全阀 + 种子语义。

覆盖 change tasks §2（角色路由）/ §3（frontier 阀）/ §4（种子只进 frontier）的
新机制。MockLLM 的 ``select_facts`` 用 callable 按当前 view 中心精确返回双角色。
"""

from __future__ import annotations

from conftest import make_query_engine, MockLLM

from mcs.core.query_engine import QueryEngine
from mcs.core.plugin_manager import PluginManager
from mcs.core.token_budget import TokenBudget
from mcs.entities.graph import Node, Subgraph
from mcs.interfaces.entry_plugin import EntryPluginInterface
from mcs.stores.in_memory import InMemoryStore


class _StaticEntry(EntryPluginInterface):
    def get_name(self) -> str:
        return "static_entry"

    def get_priority(self) -> int:
        return 100

    def __init__(self, node_ids, graph):
        self._ids = node_ids
        self._graph = graph

    def locate(self, query, ctx):
        return [
            n for n in (self._graph.get_node(i) for i in self._ids) if n is not None
        ]


def _chain_graph() -> InMemoryStore:
    """S → A → B（关联边，既是层级下钻也是关系）。"""
    g = InMemoryStore()
    for nid, name in [("S", "种子"), ("A", "甲"), ("B", "乙")]:
        g.add_node(Node(id=nid, name=name, content=name))
    g.add_edge("S", "A")
    g.add_edge("A", "B")
    return g


def _idx_of(nodes_in, node_id) -> int:
    """view_nodes 中 node_id 的 1-based 编号。"""
    return [n.id for n in (nodes_in or [])].index(node_id) + 1


# === 角色路由：探索 vs 结果解耦 ===


def test_explore_role_drives_frontier_not_accumulated():
    """`探索` 角色进 frontier 驱动展开，但不进 accumulated（结果）。"""
    g = _chain_graph()
    mock = MockLLM()

    def resp(nodes_in, _free):
        center = nodes_in[0].id
        if center == "S":
            # S 标结果、A 仅标探索（A 驱动展开但不进结果）
            return {"result": [_idx_of(nodes_in, "S")], "frontier": [_idx_of(nodes_in, "A")]}
        if center == "A":
            # 经探索 A 展开到 B，B 标结果
            return {"result": [_idx_of(nodes_in, "B")], "frontier": []}
        return {"result": [], "frontier": []}

    mock.set_response("select_facts", resp)
    engine = make_query_engine(g, mock, _StaticEntry(["S"], g), max_rounds=3)
    result = engine.query("trace")
    ids = {n.id for n in result.nodes}
    assert "S" in ids          # 结果
    assert "B" in ids          # 经探索 A 展开后标结果
    assert "A" not in ids      # 仅探索 → 不进 accumulated（解耦核心断言）


def test_both_role_in_accumulated_and_expands():
    """`两者` 角色（同时在 result/frontier）：进 accumulated 且驱动展开。"""
    g = _chain_graph()
    mock = MockLLM()

    def resp(nodes_in, _free):
        center = nodes_in[0].id
        if center == "S":
            # A 同时标结果与探索
            ia = _idx_of(nodes_in, "A")
            return {"result": [_idx_of(nodes_in, "S"), ia], "frontier": [ia]}
        if center == "A":
            return {"result": [_idx_of(nodes_in, "B")], "frontier": []}
        return {"result": [], "frontier": []}

    mock.set_response("select_facts", resp)
    engine = make_query_engine(g, mock, _StaticEntry(["S"], g), max_rounds=3)
    result = engine.query("trace")
    ids = {n.id for n in result.nodes}
    assert "A" in ids   # 两者 → 进 accumulated
    assert "B" in ids   # 两者 → A 也驱动展开到 B


# === 事实边端点随角色 ===


def test_result_edge_endpoints_to_accumulated():
    """事实边标 `结果` → 记 selected_edges、两端点进 accumulated。"""
    g = _chain_graph()
    mock = MockLLM()

    def resp(nodes_in, _free):
        if nodes_in[0].id == "S":
            # 边 S—A 是编号 n_nodes+1（节点在前、边在后）
            return {"result": [len(nodes_in) + 1], "frontier": []}
        return {"result": [], "frontier": []}

    mock.set_response("select_facts", resp)
    engine = make_query_engine(g, mock, _StaticEntry(["S"], g), max_rounds=1)
    result = engine.query("edge")
    ids = {n.id for n in result.nodes}
    assert "S" in ids and "A" in ids       # 边端点进 accumulated
    assert any(e.source_id == "S" and e.target_id == "A" for e in result.edges)


def test_explore_edge_endpoints_not_accumulated():
    """事实边标 `探索` → 端点只进 frontier，不进 accumulated。"""
    g = _chain_graph()
    mock = MockLLM()

    def resp(nodes_in, _free):
        if nodes_in[0].id == "S":
            return {"result": [], "frontier": [len(nodes_in) + 1]}
        return {"result": [], "frontier": []}

    mock.set_response("select_facts", resp)
    engine = make_query_engine(g, mock, _StaticEntry(["S"], g), max_rounds=3)
    result = engine.query("edge")
    # 无任何条目标结果 → accumulated 为空
    assert result.nodes == []


# === frontier 安全阀 ===


def _star_graph() -> InMemoryStore:
    """S →{A, B}；A→A2，B→B2（两条独立分支，各自一个孙子）。"""
    g = InMemoryStore()
    for nid in ["S", "A", "B", "A2", "B2"]:
        g.add_node(Node(id=nid, name=nid, content=nid))
    g.add_edge("S", "A")
    g.add_edge("S", "B")
    g.add_edge("A", "A2")
    g.add_edge("B", "B2")
    return g


def _star_resp(nodes_in, _free):
    """batch-robust：按 node id 定角色（不依赖 center，兼容多中心合并调用）。

    S → 结果；A/B → 两者（结果+探索，驱动展开）；A2/B2 → 结果（叶子答案）。
    """
    result, frontier = [], []
    for i, n in enumerate(nodes_in or [], 1):
        if n.id == "S":
            result.append(i)
        elif n.id in ("A", "B"):
            result.append(i)
            frontier.append(i)
        elif n.id in ("A2", "B2"):
            result.append(i)
    return {"result": result, "frontier": frontier}


def test_frontier_valve_caps_next_frontier():
    """max_frontier_nodes 限制单轮 next_frontier；被挤出的分支不再展开，但结果不丢。"""
    g = _star_graph()
    mock = MockLLM()
    mock.set_response("select_facts", _star_resp)
    # valve=1：round1 只有一个分支入 next_frontier，另一个被挤出 → 只展开其一。
    # 注：store 的 get_out_hierarchy 是 set 序，存活的是 A 还是 B 不确定，故只断言
    # 「恰有一个分支被展开」这一与顺序无关的性质（安全阀语义）。
    engine = make_query_engine(
        g, mock, _StaticEntry(["S"], g), max_rounds=3, max_frontier_nodes=1
    )
    result = engine.query("star")
    ids = {n.id for n in result.nodes}
    assert "A" in ids and "B" in ids       # 结果不受阀影响（A、B 均进 accumulated）
    assert len({"A2", "B2"} & ids) == 1    # 阀挤出一支 → 恰一个孙子被展开


def test_frontier_valve_disabled_expands_all():
    """阀放宽（默认 500）时两分支都展开（对照 valve=1）。"""
    g = _star_graph()
    mock = MockLLM()
    mock.set_response("select_facts", _star_resp)
    engine = make_query_engine(g, mock, _StaticEntry(["S"], g), max_rounds=3)
    result = engine.query("star")
    ids = {n.id for n in result.nodes}
    assert {"A2", "B2"} <= ids   # 两分支都展开


# === 种子语义（只进 frontier，不进初始 visited）===


def test_seed_enters_accumulated_only_when_result():
    """种子首轮标 `结果` 才进 accumulated（验证种子不在初始 visited，否则被跳过）。"""
    g = _chain_graph()
    mock = MockLLM()
    # 只把中心(种子)标结果
    mock.set_response("select_facts", {"result": [1], "frontier": []})
    engine = make_query_engine(g, mock, _StaticEntry(["S"], g), max_rounds=1)
    result = engine.query("seed")
    assert [n.id for n in result.nodes] == ["S"]


def test_seed_not_selected_returns_empty():
    """种子未被标任何角色 → 不进 accumulated → 空结果（种子无预填兜底）。"""
    g = _chain_graph()
    mock = MockLLM()
    mock.set_response("select_facts", {"result": [], "frontier": []})
    engine = make_query_engine(g, mock, _StaticEntry(["S"], g), max_rounds=3)
    result = engine.query("seed")
    assert isinstance(result, Subgraph)
    assert result.nodes == []


def test_visited_prevents_duplicate_accumulation():
    """visited 防重：同一节点跨轮不重复进 accumulated。"""
    g = _chain_graph()
    mock = MockLLM()

    def resp(nodes_in, _free):
        # 每轮把当前 view 全部节点标两者（含已 visited 的中心）
        n = len(nodes_in)
        all_idx = list(range(1, n + 1))
        return {"result": all_idx, "frontier": all_idx}

    mock.set_response("select_facts", resp)
    engine = make_query_engine(g, mock, _StaticEntry(["S"], g), max_rounds=5)
    result = engine.query("dup")
    ids = [n.id for n in result.nodes]
    assert sorted(ids) == ["A", "B", "S"]   # 各一次，无重复
    assert len(ids) == len(set(ids))


def test_max_frontier_nodes_in_init_signature():
    """QueryEngine.__init__ 暴露 max_frontier_nodes（默认 500）。"""
    g = _chain_graph()
    engine = QueryEngine(
        store=g,
        llm=MockLLM(),  # type: ignore[arg-type]
        plugin_manager=PluginManager(),
        token_budget=TokenBudget(8000),
    )
    assert engine.max_frontier_nodes == 500

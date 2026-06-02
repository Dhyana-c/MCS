"""FanoutReducerPlugin 测试。覆盖 subgraph-bounding tasks 2.3（token-aware 阈值）。

§3（真正建中间节点 + 重组边）的测试在 run 实装后追加。
"""

from __future__ import annotations

from mcs.core.decisions import HubDecision
from mcs.core.graph import GraphStore, Node
from mcs.core.token_budget import TokenBudget
from mcs.plugins.phase1.fanout_reducer import FanoutReducerPlugin


def _graph_with_fanout(n_neighbors: int, content: str):
    g = GraphStore()
    hub = Node(id="hub", name="hub", content=content)
    g.add_node(hub)
    for i in range(n_neighbors):
        g.add_node(Node(id=f"n{i}", name=f"n{i}", content=content))
        g.add_edge("hub", f"n{i}")
    return g, hub


def _plugin(token_budget: TokenBudget, floor: int = 16) -> FanoutReducerPlugin:
    p = FanoutReducerPlugin({"floor": floor})
    p.token_budget = token_budget  # 模拟 initialize 注入
    return p


def test_below_floor_never_triggers():
    # 10 邻居 < floor 16 → 一定不触发
    g, hub = _graph_with_fanout(10, "a" * 400)
    p = _plugin(TokenBudget(1000), floor=16)
    assert p.should_run([hub], g) is False


def test_exceeds_window_triggers():
    # 每节点 "a"*400 ≈ 100 token；50 邻居 → 累计远超小窗口
    g, hub = _graph_with_fanout(50, "a" * 400)
    p = _plugin(TokenBudget(2000), floor=16)
    assert p.should_run([hub], g) is True


def test_threshold_scales_with_window():
    # 同一邻域（~2100 token）：小窗口触发、大窗口不触发（阈值随窗口自适应）
    g, hub = _graph_with_fanout(20, "a" * 400)
    assert _plugin(TokenBudget(1000)).should_run([hub], g) is True
    assert _plugin(TokenBudget(16000)).should_run([hub], g) is False


# ─── 3.4 run：真正建中间节点 + 星型重组边 ─────────────────────────────────────


def test_run_synthetic_creates_hub_and_reorganizes():
    g, node = _graph_with_fanout(20, "a" * 400)  # node.id="hub"，20 邻居
    p = _plugin(TokenBudget(500), floor=16)  # 小窗口 → 触发，batch 取若干

    def llm(purpose, nodes_in, free_args):
        return HubDecision(hub_id=None, synthetic_hub_summary="Cluster A")

    before = len(g.get_neighbors("hub"))
    p.run([node], g, llm)

    new_hubs = [n for n in g.get_all_nodes() if n.role == "hub" and n.id != "hub"]
    assert len(new_hubs) == 1  # 真正新建了一个合成中间节点
    nh = new_hubs[0]
    assert nh.content == "Cluster A"
    assert nh.id in {n.id for n in g.get_neighbors("hub")}  # node 连到新 hub
    assert len(g.get_neighbors(nh.id)) >= 2  # 成员改挂到新 hub
    assert len(g.get_neighbors("hub")) < before  # node 度下降（fanout 被收敛）


def test_run_promotes_existing_node_as_hub():
    g, node = _graph_with_fanout(20, "a" * 400)
    p = _plugin(TokenBudget(500), floor=16)

    def llm(purpose, nodes_in, free_args):
        return HubDecision(hub_id="n0", synthetic_hub_summary=None)  # 提拔现有 n0

    p.run([node], g, llm)
    assert g.get_node("n0").role == "hub"
    assert len(g.get_neighbors("n0")) >= 2  # 其他成员收敛到 n0


def test_run_skips_when_under_budget():
    # 大窗口装得下 → 不触发归纳，不建任何 hub
    g, node = _graph_with_fanout(20, "a" * 400)
    p = _plugin(TokenBudget(16000), floor=16)
    p.run([node], g, lambda *a, **k: HubDecision(hub_id=None, synthetic_hub_summary="X"))
    assert [n for n in g.get_all_nodes() if n.role == "hub"] == []

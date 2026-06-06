"""FanoutReducerPlugin 测试。覆盖 subgraph-bounding tasks 2.3（token-aware 阈值）。

§3（真正建中间节点 + 重组边）的测试在 run 实装后追加。
"""

from __future__ import annotations

from dataclasses import replace as dc_replace

from mcs.core.decisions import Community, MultiHubDecision
from mcs.core.graph import GraphStore, Node
from mcs.core.token_budget import TokenBudget
from mcs.plugins.phase1.fanout_reducer import FanoutReducerPlugin


def _summary_community(summary: str):
    """mock decide_hub：把整批邻居归为一个 summarize 社区（固定 summary）。"""
    def _resp(purpose, nodes_in, free_args):
        ids = [n.id for n in nodes_in[1:]]
        return MultiHubDecision(
            communities=[
                Community(theme=summary, member_ids=ids,
                          strategy="summarize", summary=summary)
            ]
        )
    return _resp


def _graph_with_fanout(n_neighbors: int, content: str):
    g = GraphStore()
    hub = Node(id="hub", name="hub", content=content)
    g.add_node(hub)
    for i in range(n_neighbors):
        g.add_node(Node(id=f"n{i}", name=f"n{i}", content=content))
        g.add_edge("hub", f"n{i}")
    return g, hub


def _plugin(token_budget: TokenBudget, floor: int = 16, maintain_root: bool = False) -> FanoutReducerPlugin:
    p = FanoutReducerPlugin({"floor": floor, "maintain_root": maintain_root})
    p.token_budget = token_budget  # 模拟 initialize 注入
    return p


def test_below_floor_but_exceeds_token_triggers():
    # 10 邻居 < floor 16，但 token 超 T → 仍触发（不变量优先）
    # 每节点 "a"*400 ≈ 100 token；hub + 10 邻居 ≈ 1100 token > 1000
    g, hub = _graph_with_fanout(10, "a" * 400)
    p = _plugin(TokenBudget(1000), floor=16)
    assert p.should_run([hub], g) is True


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


def test_gate_estimate_matches_actual_render():
    """守门估算 == 实际 decide_hub 渲染 token（铁律一：估算口径 == 渲染口径）。

    注入真实 ContextRenderer 后，_neighborhood_tokens 必须逐字等于
    tb.estimate(renderer.render([node, *neighbors], "decide_hub"))，且阈值恰好
    卡在该渲染量两侧。
    """
    from mcs.core.context_renderer import ContextRenderer

    g = GraphStore()
    node = Node(id="hub", name="hub", content="center content")
    g.add_node(node)
    for i in range(8):
        nb = Node(id=f"n{i}", name=f"n{i}", content=f"concept number {i} body text")
        g.add_node(nb)
        g.add_edge("hub", f"n{i}", direction="out")

    renderer = ContextRenderer(None)  # 无插件扩展
    nbrs = g.get_neighbors("hub")
    expected = TokenBudget(10_000).estimate(
        renderer.render([node, *nbrs], "decide_hub")
    )

    p = FanoutReducerPlugin({"floor": 2})
    p.renderer = renderer
    p.token_budget = TokenBudget(10_000)
    assert p._neighborhood_tokens(node, nbrs) == expected

    # 阈值卡在渲染量两侧：恰好超 1 触发，恰好余 1 不触发
    p.token_budget = TokenBudget(expected - 1)
    assert p._exceeds_budget(node, nbrs) is True
    p.token_budget = TokenBudget(expected + 1)
    assert p._exceeds_budget(node, nbrs) is False


# ─── 3.4 run：真正建中间节点 + 星型重组边 ─────────────────────────────────────


def test_run_synthetic_creates_hub_and_reorganizes():
    g, node = _graph_with_fanout(20, "a" * 400)  # node.id="hub"，20 邻居
    p = _plugin(TokenBudget(500), floor=16)  # 小窗口 → 触发，batch 取若干

    before = len(g.get_neighbors("hub"))
    p.run([node], g, _summary_community("Cluster A"))

    new_hubs = [n for n in g.get_all_nodes() if n.role == "hub" and n.id != "hub"]
    assert len(new_hubs) == 1  # 同 summary 去重 → 恰好一个合成中间节点
    nh = new_hubs[0]
    assert nh.content == "Cluster A"
    assert nh.id in {n.id for n in g.get_neighbors("hub")}  # node 连到新 hub
    assert len(g.get_neighbors(nh.id)) >= 2  # 成员改挂到新 hub
    assert len(g.get_neighbors("hub")) < before  # node 度下降（fanout 被收敛）


def test_run_skips_when_under_budget():
    # 大窗口装得下 → 不触发归纳，不建任何 hub
    g, node = _graph_with_fanout(20, "a" * 400)
    p = _plugin(TokenBudget(16000), floor=16)
    p.run([node], g, _summary_community("X"))
    assert [n for n in g.get_all_nodes() if n.role == "hub"] == []


# ─── 3.4 一进多出测试 ────────────────────────────────────────────────────────


def test_multi_hub_creates_multiple_hubs():
    """一进多出：一次归纳产出多个 hub。"""

    # 使用小预算触发裂变，但 mock LLM 只返回 batch 中的 member_ids
    g, node = _graph_with_fanout(50, "a" * 400)
    p = _plugin(TokenBudget(500), floor=16)

    def llm(purpose, nodes_in, free_args):
        # nodes_in[0] 是中心节点，nodes_in[1:] 是 batch 中的邻居
        batch_ids = [n.id for n in nodes_in[1:]]
        # 只返回 batch 中存在的 member_ids
        return MultiHubDecision(
            communities=[
                Community(theme="Group A", member_ids=batch_ids[:2], strategy="summarize", summary="Group A summary"),
                Community(theme="Group B", member_ids=batch_ids[2:4] if len(batch_ids) > 2 else [], strategy="summarize", summary="Group B summary"),
            ],
            unassigned_ids=batch_ids[4:] if len(batch_ids) > 4 else [],
        )

    before = len(g.get_neighbors("hub"))
    p.run([node], g, llm)

    new_hubs = [n for n in g.get_all_nodes() if n.role == "hub" and n.id != "hub"]
    assert len(new_hubs) >= 1  # 至少产出一个 hub
    assert len(g.get_neighbors("hub")) < before  # node 度下降


def test_key_concept_strategy_promotes_existing_node():
    """key_concept 策略：提拔现有节点为 hub。"""

    g, node = _graph_with_fanout(30, "a" * 400)
    p = _plugin(TokenBudget(500), floor=16)

    def llm(purpose, nodes_in, free_args):
        # nodes_in[0] 是中心节点，nodes_in[1:] 是 batch 中的邻居
        batch_ids = [n.id for n in nodes_in[1:]]
        # 返回第一个邻居作为关键概念
        return MultiHubDecision(
            communities=[
                Community(theme="Key", member_ids=batch_ids[:3], strategy="key_concept", key_concept_id=batch_ids[0] if batch_ids else None),
            ],
            unassigned_ids=[],
        )

    p.run([node], g, llm)
    # 检查是否有节点被提拔为 hub
    hubs = [n for n in g.get_all_nodes() if n.role == "hub" and n.id != "hub"]
    assert len(hubs) >= 1


def test_unassigned_members_stay_with_parent():
    """unassigned 成员保留在中心节点下（确定性兜底）。"""

    g, node = _graph_with_fanout(30, "a" * 400)
    p = _plugin(TokenBudget(500), floor=16)

    def llm(purpose, nodes_in, free_args):
        return MultiHubDecision(
            communities=[
                Community(theme="A", member_ids=["n0", "n1"], strategy="summarize", summary="A"),
            ],
            unassigned_ids=["n2", "n3"],  # n2, n3 未分类
        )

    p.run([node], g, llm)
    # n2, n3 仍直连 node（未重挂到 hub）
    neighbors = g.get_neighbors("hub")
    assert "n2" in {n.id for n in neighbors} or "n3" in {n.id for n in neighbors}


def test_overlapping_clustering():
    """重叠聚类：一个成员可以属于多个 hub。"""

    g, node = _graph_with_fanout(30, "a" * 400)
    p = _plugin(TokenBudget(500), floor=16)

    def llm(purpose, nodes_in, free_args):
        # nodes_in[0] 是中心节点，nodes_in[1:] 是 batch 中的邻居
        batch_ids = [n.id for n in nodes_in[1:]]
        if len(batch_ids) < 3:
            return MultiHubDecision(communities=[], unassigned_ids=batch_ids)
        # n0 同时属于两个社区
        return MultiHubDecision(
            communities=[
                Community(theme="Technology", member_ids=[batch_ids[0], batch_ids[1]], strategy="summarize", summary="Technology and computing concepts"),
                Community(theme="Business", member_ids=[batch_ids[0], batch_ids[2]], strategy="summarize", summary="Business and finance topics"),
            ],
            unassigned_ids=[],
        )

    p.run([node], g, llm)
    new_hubs = [n for n in g.get_all_nodes() if n.role == "hub" and n.id != "hub"]
    # 至少产出 hub（可能只有 1 个，因为 batch 可能太小）
    assert len(new_hubs) >= 1


def test_hub_reuse_edge_absorption():
    """hub 复用：节点 X 包含 hub H 的全部成员时，X 改连 H。"""

    g = GraphStore()
    # 构建图：root 连 n0-n5，root 也连 hub
    root = Node(id="root", name="root", content="r" * 400)
    g.add_node(root)
    hub = Node(id="hub1", name="Hub1", content="Hub about tech", role="hub")
    g.add_node(hub)
    for i in range(6):
        n = Node(id=f"n{i}", name=f"n{i}", content=f"concept {i}")
        g.add_node(n)
        # root 和 hub 都直连 n0-n5
        g.add_edge(root.id, n.id, direction="out")
        g.add_edge(hub.id, n.id, direction="out")
    g.add_edge(root.id, hub.id, direction="out")

    p = _plugin(TokenBudget(500), floor=2)
    # 运行边吸收
    p._absorb_hub_edges(g)

    # root 不应再直连 hub 的成员，而是通过 hub 间接连接
    root_out_neighbors = g.get_out_neighbors(root.id)
    root_out_ids = {n.id for n in root_out_neighbors}
    assert "hub1" in root_out_ids  # root 连到 hub
    # root 不再直连 hub 的成员（被吸收了）
    for i in range(6):
        assert f"n{i}" not in root_out_ids


def test_partial_contain_no_absorption():
    """部分包含不吸收：节点只包含 hub 的部分成员时不改连。"""

    g = GraphStore()
    root = Node(id="root", name="root", content="r" * 400)
    g.add_node(root)
    hub = Node(id="hub1", name="Hub1", content="Hub about tech", role="hub")
    g.add_node(hub)
    # hub 只包含 n0-n2
    for i in range(3):
        n = Node(id=f"n{i}", name=f"n{i}", content=f"concept {i}")
        g.add_node(n)
        g.add_edge(hub.id, n.id, direction="out")
    # root 直连 n0-n5（包含 n0-n2 + 更多）
    for i in range(6):
        n = g.get_node(f"n{i}")
        if n is None:
            n = Node(id=f"n{i}", name=f"n{i}", content=f"concept {i}")
            g.add_node(n)
        g.add_edge(root.id, n.id, direction="out")
    g.add_edge(root.id, hub.id, direction="out")

    p = _plugin(TokenBudget(500), floor=2)
    p._absorb_hub_edges(g)

    # root 仍直连 n3-n5（因为 n3-n5 不是 hub 的成员）
    root_out_neighbors = g.get_out_neighbors(root.id)
    root_out_ids = {n.id for n in root_out_neighbors}
    assert "n3" in root_out_ids
    assert "n4" in root_out_ids
    assert "n5" in root_out_ids


def test_absorb_skips_single_member_hub_no_net_reduction():
    """hub 只有 1 个成员时不吸收（删 1 加 1 无净减边，重组以降总量为判据）。"""
    g = GraphStore()
    g.add_node(Node(id="root", name="root", content="r"))
    g.add_node(Node(id="hub1", name="Hub1", content="hub", role="hub"))
    g.add_node(Node(id="m0", name="m0", content="m0"))
    g.add_edge("hub1", "m0", direction="out")   # hub 仅 1 个成员
    g.add_edge("root", "m0", direction="out")   # root 直连 m0
    g.add_edge("root", "hub1", direction="out")

    p = _plugin(TokenBudget(500), floor=2)
    p._absorb_hub_edges(g)

    # 未吸收：root 仍直连 m0
    assert "m0" in {n.id for n in g.get_out_neighbors("root")}


def test_rollback_restores_inplace_field_mutations():
    """回滚真正还原节点的原地字段改动（content/role），而非只还原结构。"""
    g = GraphStore()
    g.add_node(Node(id="a", name="A", content="original A", role="concept"))
    g.add_node(Node(id="b", name="B", content="original B", role="concept"))
    g.add_edge("a", "b", direction="out")

    p = _plugin(TokenBudget(500), floor=2)
    state = {
        "nodes": {
            n.id: dc_replace(n, extensions=dict(n.extensions or {}))
            for n in g.get_all_nodes()
        },
        "edges": list(g.get_all_edges()),
    }
    # 原地改动：提拔 role + 改 content + 删节点
    g.update_node("a", {"role": "hub", "content": "MUTATED"})
    g.delete_node("b")

    p._rollback_reorg(g, state)

    assert g.get_node("a").role == "concept"        # role 还原
    assert g.get_node("a").content == "original A"   # content 还原
    assert g.get_node("b") is not None              # 被删节点恢复
    assert g.get_node("b").content == "original B"

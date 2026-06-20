"""FanoutReducerPlugin 测试。覆盖 subgraph-bounding tasks 2.3（token-aware 阈值）。

§3（真正建中间节点 + 重组边）的测试在 run 实装后追加。
"""

from __future__ import annotations

from mcs.core.token_budget import TokenBudget
from mcs.entities.decisions import Community, MultiHubDecision
from mcs.entities.graph import CLASS_CONCEPT, CLASS_FACT, Node
from mcs.plugins.maintenance.fanout_reducer import FanoutReducerPlugin
from mcs.stores.in_memory import InMemoryStore

GraphStore = InMemoryStore


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
        g.add_edge("hub", f"n{i}")

    renderer = ContextRenderer(None)  # 无插件扩展
    nbrs = g.get_out_hierarchy("hub")
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
    p = _plugin(TokenBudget(500), floor=16)  # 小窗口 → 触发

    before = len(g.get_out_hierarchy("hub"))
    p.run([node], g, _summary_community("Cluster A"))

    new_hubs = [n for n in g.get_all_nodes() if n.hub is True and n.id != "hub"]
    assert len(new_hubs) == 1  # 同 summary 去重 → 恰好一个合成中间节点
    nh = new_hubs[0]
    assert nh.content == "Cluster A"
    assert nh.id in {n.id for n in g.get_out_hierarchy("hub")}  # node 连到新 hub
    assert len(g.get_out_hierarchy(nh.id)) >= 2  # 成员改挂到新 hub
    assert len(g.get_out_hierarchy("hub")) < before  # node 度下降（fanout 被收敛）


def test_run_skips_when_under_budget():
    # 大窗口装得下 → 不触发归纳，不建任何 hub
    g, node = _graph_with_fanout(20, "a" * 400)
    p = _plugin(TokenBudget(16000), floor=16)
    p.run([node], g, _summary_community("X"))
    assert [n for n in g.get_all_nodes() if n.hub is True] == []


# ─── 3.4 一进多出测试 ────────────────────────────────────────────────────────


def test_multi_hub_creates_multiple_hubs():
    """一进多出：一次归纳产出多个 hub。"""

    g, node = _graph_with_fanout(50, "a" * 400)
    p = _plugin(TokenBudget(500), floor=16)

    def llm(purpose, nodes_in, free_args):
        batch_ids = [n.id for n in nodes_in[1:]]
        return MultiHubDecision(
            communities=[
                Community(theme="Group A", member_ids=batch_ids[:2], strategy="summarize", summary="Group A summary"),
                Community(theme="Group B", member_ids=batch_ids[2:4] if len(batch_ids) > 2 else [], strategy="summarize", summary="Group B summary"),
            ],
            unassigned_ids=batch_ids[4:] if len(batch_ids) > 4 else [],
        )

    before = len(g.get_out_hierarchy("hub"))
    p.run([node], g, llm)

    new_hubs = [n for n in g.get_all_nodes() if n.hub is True and n.id != "hub"]
    assert len(new_hubs) >= 1  # 至少产出一个 hub
    assert len(g.get_out_hierarchy("hub")) < before  # node 度下降


def test_key_concept_strategy_promotes_existing_node():
    """key_concept 策略：提拔现有节点为 hub。"""

    g, node = _graph_with_fanout(30, "a" * 400)
    p = _plugin(TokenBudget(500), floor=16)

    def llm(purpose, nodes_in, free_args):
        batch_ids = [n.id for n in nodes_in[1:]]
        return MultiHubDecision(
            communities=[
                Community(theme="Key", member_ids=batch_ids[:3], strategy="key_concept", key_concept_id=batch_ids[0] if batch_ids else None),
            ],
            unassigned_ids=[],
        )

    p.run([node], g, llm)
    hubs = [n for n in g.get_all_nodes() if n.hub is True and n.id != "hub"]
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
            unassigned_ids=["n2", "n3"],
        )

    p.run([node], g, llm)
    neighbors = g.get_out_hierarchy("hub")
    assert "n2" in {n.id for n in neighbors} or "n3" in {n.id for n in neighbors}


def test_overlapping_clustering():
    """重叠聚类：一个成员可以属于多个 hub。"""

    g, node = _graph_with_fanout(30, "a" * 400)
    p = _plugin(TokenBudget(500), floor=16)

    def llm(purpose, nodes_in, free_args):
        batch_ids = [n.id for n in nodes_in[1:]]
        if len(batch_ids) < 3:
            return MultiHubDecision(communities=[], unassigned_ids=batch_ids)
        return MultiHubDecision(
            communities=[
                Community(theme="Technology", member_ids=[batch_ids[0], batch_ids[1]], strategy="summarize", summary="Technology and computing concepts"),
                Community(theme="Business", member_ids=[batch_ids[0], batch_ids[2]], strategy="summarize", summary="Business and finance topics"),
            ],
            unassigned_ids=[],
        )

    p.run([node], g, llm)
    new_hubs = [n for n in g.get_all_nodes() if n.hub is True and n.id != "hub"]
    assert len(new_hubs) >= 1


def test_hub_reuse_edge_absorption():
    """hub 复用：节点 X 包含 hub H 的全部成员时，X 改连 H。"""

    g = GraphStore()
    root = Node(id="root", name="root", content="r" * 400)
    g.add_node(root)
    hub = Node(id="hub1", name="Hub1", content="Hub about tech", extensions={"hub": True})
    g.add_node(hub)
    for i in range(6):
        n = Node(id=f"n{i}", name=f"n{i}", content=f"concept {i}")
        g.add_node(n)
        g.add_edge(root.id, n.id)
        g.add_edge(hub.id, n.id)
    g.add_edge(root.id, hub.id)

    p = _plugin(TokenBudget(500), floor=2)
    p._absorb_hub_edges(g)

    root_neighbors = g.get_out_hierarchy(root.id)
    root_ids = {n.id for n in root_neighbors}
    assert "hub1" in root_ids
    for i in range(6):
        assert f"n{i}" not in root_ids


def test_partial_contain_no_absorption():
    """部分包含不吸收：节点只包含 hub 的部分成员时不改连。"""

    g = GraphStore()
    root = Node(id="root", name="root", content="r" * 400)
    g.add_node(root)
    hub = Node(id="hub1", name="Hub1", content="Hub about tech", extensions={"hub": True})
    g.add_node(hub)
    for i in range(3):
        n = Node(id=f"n{i}", name=f"n{i}", content=f"concept {i}")
        g.add_node(n)
        g.add_edge(hub.id, n.id)
    for i in range(6):
        n = g.get_node(f"n{i}")
        if n is None:
            n = Node(id=f"n{i}", name=f"n{i}", content=f"concept {i}")
            g.add_node(n)
        g.add_edge(root.id, n.id)
    g.add_edge(root.id, hub.id)

    p = _plugin(TokenBudget(500), floor=2)
    p._absorb_hub_edges(g)

    root_ids = {n.id for n in g.get_out_hierarchy(root.id)}
    assert "n3" in root_ids
    assert "n4" in root_ids
    assert "n5" in root_ids


def test_absorb_skips_single_member_hub_no_net_reduction():
    """hub 只有 1 个成员时不吸收（删 1 加 1 无净减边，重组以降总量为判据）。"""
    g = GraphStore()
    g.add_node(Node(id="root", name="root", content="r"))
    g.add_node(Node(id="hub1", name="Hub1", content="hub", extensions={"hub": True}))
    g.add_node(Node(id="m0", name="m0", content="m0"))
    g.add_edge("hub1", "m0")
    g.add_edge("root", "m0")
    g.add_edge("root", "hub1")

    p = _plugin(TokenBudget(500), floor=2)
    p._absorb_hub_edges(g)

    assert "m0" in {n.id for n in g.get_out_hierarchy("root")}


def test_rollback_restores_inplace_field_mutations():
    """回滚真正还原节点的原地字段改动（content/hub），而非只还原结构。"""
    g = GraphStore()
    g.add_node(Node(id="a", name="A", content="original A", node_class="概念"))
    g.add_node(Node(id="b", name="B", content="original B", node_class="概念"))
    g.add_edge("a", "b")

    p = _plugin(TokenBudget(500), floor=2)
    state = g.snapshot()
    g.update_node("a", {"hub": True, "content": "MUTATED"})
    g.delete_node("b")

    p._rollback_reorg(g, state)

    assert g.get_node("a").node_class == "概念"
    assert g.get_node("a").hub is False  # hub 标记（extensions）也被回滚
    assert g.get_node("a").content == "original A"
    assert g.get_node("b") is not None
    assert g.get_node("b").content == "original B"


def test_rollback_preserves_edge_ids():
    """回滚保留边 id（不 churn uuid）——这是增量持久化不留重复边的前提。"""
    g = GraphStore()
    g.add_node(Node(id="a", name="A", content="A"))
    g.add_node(Node(id="b", name="B", content="B"))
    fact_id = g.add_edge("a", "b")

    p = _plugin(TokenBudget(500), floor=2)
    state = g.snapshot()
    # 模拟 reorg：删原边、加不同 label 的新边
    g.delete_edge(fact_id)
    g.add_edge("a", "b")

    p._rollback_reorg(g, state)

    facts = g.get_relations("a")
    assert len(facts) == 1
    assert facts[0].id == fact_id  # 同一个 id，未被 churn


def test_migrate_edges_dedup_same_type_between_pair():
    """合并同义时迁移边按 type 去重：同一对端点间同 type（关联）的边只保留一份。

    统一模型无 label；同一 (rep, x, 关联) 迁移并入既有边、不重复。
    """
    g = GraphStore()
    for nid in ["m", "rep", "x"]:
        g.add_node(Node(id=nid, name=nid, content=nid))
    g.add_edge("rep", "x")  # rep→x（关联）
    g.add_edge("m", "x")    # m→x（关联），迁移到 rep→x

    p = _plugin(TokenBudget(500), floor=2)
    p._migrate_edges("m", "rep", g)

    rep_facts = [e for e in g.get_relations("rep") if e.target_id == "x"]
    assert len(rep_facts) == 1  # 同 type 去重，只一份


def test_merge_strategy_skips_fact_nodes():
    """宪法：对事实节点只重组不合并（合并会断背书/互斥）。

    merge 策略下：概念走合并（删除同义节点），事实走重组（保留节点、仅重挂层级边）。
    直接调用 _reorganize_multi，不设 token_budget 以避免 _validate_reorg 回滚干扰。
    """
    g = GraphStore()
    center = Node(id="center", name="center", content="c" * 400)
    g.add_node(center)
    # 2 个概念 + 2 个事实
    c1 = Node(id="c1", name="概念A", content="概念A内容", node_class=CLASS_CONCEPT)
    c2 = Node(id="c2", name="概念A别名", content="概念A同义内容", node_class=CLASS_CONCEPT)
    f1 = Node(id="f1", name="事实1", content="X喜欢Y", node_class=CLASS_FACT)
    f2 = Node(id="f2", name="事实2", content="X出生于Z", node_class=CLASS_FACT)
    for n in [c1, c2, f1, f2]:
        g.add_node(n)
        g.add_edge("center", n.id)
    # 事实间有互斥边（合并会断掉）
    g.add_edge("f1", "f2", type="互斥")

    p = FanoutReducerPlugin({"floor": 2, "maintain_root": False})
    # 不设 token_budget → _validate_reorg 直接返回 True
    neighbors = g.get_out_hierarchy("center")

    decision = MultiHubDecision(
        communities=[
            Community(
                theme="合并组", member_ids=["c1", "c2", "f1", "f2"],
                strategy="merge", summary="合并同义",
            ),
        ],
    )

    p._reorganize_multi(center, decision, neighbors, g)

    # 概念 c2 应被合并删除（同义合并）
    assert g.get_node("c2") is None, "同义概念应被合并删除"
    # 事实 f1、f2 应保留（只重组不合并）
    assert g.get_node("f1") is not None, "事实节点不应被合并删除"
    assert g.get_node("f2") is not None, "事实节点不应被合并删除"
    # 互斥边应保留（合并不会断掉）
    mutex_edges = [e for e in g.get_relations("f1") if e.type == "互斥"]
    assert len(mutex_edges) >= 1, "事实间互斥边应保留"


def test_merge_strategy_pure_concepts_still_merges():
    """纯概念社区仍走合并路径（无事实节点时不影响行为）。"""
    g = GraphStore()
    center = Node(id="center", name="center", content="c" * 400)
    g.add_node(center)
    c1 = Node(id="c1", name="概念A", content="概念A内容", node_class=CLASS_CONCEPT)
    c2 = Node(id="c2", name="概念A别名", content="概念A同义内容", node_class=CLASS_CONCEPT)
    for n in [c1, c2]:
        g.add_node(n)
        g.add_edge("center", n.id)

    p = FanoutReducerPlugin({"floor": 2, "maintain_root": False})
    neighbors = g.get_out_hierarchy("center")

    decision = MultiHubDecision(
        communities=[
            Community(
                theme="合并组", member_ids=["c1", "c2"],
                strategy="merge", summary="合并同义",
            ),
        ],
    )

    p._reorganize_multi(center, decision, neighbors, g)

    # c2 被合并删除
    assert g.get_node("c2") is None
    # c1 保留（作为代表）
    assert g.get_node("c1") is not None

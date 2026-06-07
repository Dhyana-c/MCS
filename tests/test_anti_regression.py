"""抗退化 bounding 测试：拒绝空洞 hub、合成 hub 去重、max_reorg 告警。

覆盖 max-context-reclustering 变更后的行为。
"""

from __future__ import annotations

import logging

from mcs.core.config import MCSConfig
from mcs.core.decisions import Community, MultiHubDecision
from mcs.core.graph import Node
from mcs.core.plugin_manager import PluginContext, PluginManager
from mcs.core.token_budget import TokenBudget
from mcs.plugins.phase1.fanout_reducer import FanoutReducerPlugin
from mcs.stores.in_memory import InMemoryStore

GraphStore = InMemoryStore


def _fanout_with_root(graph, token_budget, mock_llm, **extra_cfg):
    pm = PluginManager()
    pm.register(mock_llm)
    cfg = {"floor": 16, **extra_cfg}
    fr = FanoutReducerPlugin(cfg)
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


def test_select_batch_returns_all_under_invariant():
    """有 token_budget 时，_select_batch 返回全部邻居（不变量保证 ≤ 窗口）。"""
    g = GraphStore()
    node = Node(id="hub", name="hub", content="a" * 400)
    g.add_node(node)
    for i in range(100):
        g.add_node(Node(id=f"n{i}", name=f"n{i}", content="a" * 400))
        g.add_edge("hub", f"n{i}", direction="bidirectional")

    fr = FanoutReducerPlugin({"floor": 16})
    fr.token_budget = TokenBudget(100000)  # 大窗口

    batch = fr._select_batch(node, g.get_neighbors("hub"))
    assert len(batch) == 100  # 不变量保证全部邻居 ≤ 窗口


def test_overbroad_hub_rejects_empty_summary():
    """空洞/过短摘要被拒绝。"""
    fr = FanoutReducerPlugin()
    assert fr._is_overbroad_hub("", member_count=5, total_neighbors=10) is True
    assert fr._is_overbroad_hub("  ", member_count=5, total_neighbors=10) is True
    assert fr._is_overbroad_hub("ab", member_count=5, total_neighbors=10) is True


def test_overbroad_hub_rejects_empty_patterns():
    """空洞聚合标签被拒绝。"""
    fr = FanoutReducerPlugin()
    assert fr._is_overbroad_hub("信息碎片集合", member_count=50, total_neighbors=100) is True
    assert fr._is_overbroad_hub("综合信息枢纽", member_count=50, total_neighbors=100) is True
    assert fr._is_overbroad_hub("其他未分类概念", member_count=50, total_neighbors=100) is True


def test_overbroad_hub_rejects_english_empty_patterns():
    """英文空洞聚合标签被拒绝（评测语料为英文）。"""
    fr = FanoutReducerPlugin()
    assert fr._is_overbroad_hub("Miscellaneous information", 50, 100) is True
    assert fr._is_overbroad_hub("Various topics and concepts", 50, 100) is True
    assert fr._is_overbroad_hub("A comprehensive node covering everything", 50, 100) is True
    assert fr._is_overbroad_hub("Uncategorized items", 5, 10) is True


def test_overbroad_hub_allows_meaningful_summary():
    """有语义内涵的摘要不被拒绝。"""
    fr = FanoutReducerPlugin()
    assert fr._is_overbroad_hub("Medical and healthcare concepts", member_count=50, total_neighbors=100) is False
    assert fr._is_overbroad_hub("Technology and computing topics", member_count=10, total_neighbors=10) is False


def test_overbroad_hub_not_created_with_empty_summary():
    """空洞 hub 被 _create_hub_from_community 拒绝，不创建节点。"""
    g = GraphStore()
    fr = FanoutReducerPlugin({"floor": 2})
    fr.token_budget = TokenBudget(500)

    comm = Community(theme="x", member_ids=[], strategy="summarize", summary="信息碎片集合")
    hub = fr._create_hub_from_community(comm, g, [])
    assert hub is None  # 被拒绝


def test_normal_hub_created_when_not_overbroad():
    """有意义摘要的 hub 正常创建。"""
    g = GraphStore()
    fr = FanoutReducerPlugin({"floor": 2})
    fr.token_budget = TokenBudget(500)

    comm = Community(
        theme="x", member_ids=[], strategy="summarize",
        summary="Medical cluster about healthcare",
    )
    hub = fr._create_hub_from_community(comm, g, [])
    assert hub is not None
    assert hub.role == "hub"


def test_similar_hub_deduplication():
    """新合成 hub 与既有 hub 近似时合并，不新建。"""
    g = GraphStore()
    existing = Node(
        id="existing_hub",
        name="Medical Hub",
        content="Medical and healthcare information cluster",
        role="hub",
    )
    g.add_node(existing)

    fr = FanoutReducerPlugin({"floor": 2})
    fr.token_budget = TokenBudget(500)

    # 摘要高度近似 → 应返回既有 hub
    similar = fr._find_similar_hub(
        "Medical and healthcare information cluster", g, threshold=0.7
    )
    assert similar is not None
    assert similar.id == "existing_hub"


def test_dissimilar_hub_not_deduplicated():
    """不近似的 hub 不被去重。"""
    g = GraphStore()
    existing = Node(
        id="sports_hub",
        name="Sports Hub",
        content="Sports and athletics information",
        role="hub",
    )
    g.add_node(existing)

    fr = FanoutReducerPlugin({"floor": 2})
    fr.token_budget = TokenBudget(500)

    similar = fr._find_similar_hub(
        "Medical and healthcare information cluster", g, threshold=0.7
    )
    assert similar is None  # 不近似


def test_max_reorg_warning_logged(mock_llm, caplog):
    """撞 max_reorg 上限时输出告警日志。"""
    g = GraphStore()
    concepts = []
    for i in range(20):
        n = Node(id=f"c{i}", name=f"c{i}", content="a" * 400, role="concept")
        g.add_node(n)
        concepts.append(n)

    # 每次都返回新 hub，让递归持续
    call_count = [0]
    def _always_hub(nodes_in, free_args):
        call_count[0] += 1
        ids = [n.id for n in nodes_in[1:]]
        # 不重复的摘要避免去重、领域词避免过宽检测 → 持续产新 hub 触发递归
        return MultiHubDecision(communities=[
            Community(theme=f"c{call_count[0]}", member_ids=ids,
                      strategy="summarize", summary=f"Cluster {call_count[0]}")
        ])

    mock_llm.set_response("decide_hub", _always_hub)

    # 直接创建 plugin，确保配置正确
    pm = PluginManager()
    pm.register(mock_llm)
    fr = FanoutReducerPlugin({
        "floor": 2, "max_reorg": 2,
        "max_hub_member_ratio": 0.9, "max_hub_summary_domains": 10,
    })
    pm.register(fr)
    pm.initialize_all(
        PluginContext(
            store=g,
            config=MCSConfig(seed_graph_bounding=True),
            token_budget=TokenBudget(500),
            context_renderer=None,  # type: ignore[arg-type]
            plugin_manager=pm,
        )
    )

    with caplog.at_level(logging.WARNING, logger="mcs.plugins.phase1.fanout_reducer"):
        changed = list(concepts)
        fr.run(changed, g, mock_llm.call)

    assert any("max_reorg" in r.message for r in caplog.records)

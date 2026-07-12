"""multi-universe-graph ingest 链路边界测试（mock LLM + WritePipeline）。

覆盖：universe 判定（work_id → canonical，不经 LLM）、event 固定现实世界、
universe 元节点自动建 + 不持成员、归一（别名命中复用 / 未命中新建宁裂）、
跨 universe 同名不合并 / 事实不互斥（**核心收益：修虚构 vs 真实误判互斥**）、
同 universe 内仍正常互斥。
"""

from __future__ import annotations

from mcs.core.plugin_manager import PluginManager
from mcs.core.query_engine import QueryEngine
from mcs.core.token_budget import TokenBudget
from mcs.core.write_pipeline import WritePipeline
from mcs.entities.decisions import ConceptDraft, Decision, EventData
from mcs.entities.graph import (
    CLASS_CONCEPT,
    CLASS_FACT,
    EDGE_MUTEX,
    REALITY_UNIVERSE,
    Node,
)


def _make_pipeline(store, mock_llm) -> WritePipeline:
    pm = PluginManager()
    pm.register(mock_llm)
    tb = TokenBudget(8000)
    qe = QueryEngine(store=store, llm=mock_llm, plugin_manager=pm, token_budget=tb)
    return WritePipeline(
        store=store,
        llm=mock_llm,
        query_engine=qe,
        plugin_manager=pm,
        token_budget=tb,
    )


def _is_universe_meta(node: Node) -> bool:
    return isinstance((node.extensions or {}).get("universe_meta"), dict)


# === 5.1 / 5.12 universe 判定（不经 LLM） ===


def test_resolve_universe_no_work_id_is_reality(empty_graph, mock_llm) -> None:
    wp = _make_pipeline(empty_graph, mock_llm)
    assert wp._resolve_universe(None) == REALITY_UNIVERSE
    assert wp._resolve_universe("") == REALITY_UNIVERSE
    # 判定不经 LLM（5.1）：整个归一/判定路径 MUST NOT 调 LLM
    assert mock_llm.call_log == []


def test_resolve_universe_with_work_id_returns_canonical(empty_graph, mock_llm) -> None:
    wp = _make_pipeline(empty_graph, mock_llm)
    assert wp._resolve_universe("三国演义") == "三国演义"
    # 判定不经 LLM（5.1）：即使建元节点也 MUST NOT 调 LLM
    assert mock_llm.call_log == []


# === 5.16 universe 元节点（自动建 + 归现实造物 + 不持成员） ===


def test_resolve_universe_creates_meta_node(empty_graph, mock_llm) -> None:
    wp = _make_pipeline(empty_graph, mock_llm)
    wp._resolve_universe("三国演义")
    metas = [n for n in empty_graph.get_all_nodes() if _is_universe_meta(n)]
    assert len(metas) == 1
    meta = metas[0]
    assert meta.node_class == CLASS_CONCEPT
    assert meta.universe == REALITY_UNIVERSE  # 作品作为现实造物 ≠ 所述世界
    assert meta.name == "三国演义"
    # 不持成员：框架 MUST NOT 自动建"成员 → 元节点"归属边
    assert empty_graph.get_out_hierarchy(meta.id) == []


# === 5.17 归一（别名命中复用 / 未命中新建宁裂） ===


def test_resolve_universe_alias_hit_reuses_canonical(empty_graph, mock_llm) -> None:
    wp = _make_pipeline(empty_graph, mock_llm)
    wp._resolve_universe("三国演义")
    assert wp.register_universe_alias("三国演义", "三国") is True
    # work_id="三国" 命中别名 → 复用 canonical "三国演义"，不新建（不误裂）
    assert wp._resolve_universe("三国") == "三国演义"
    metas = [n for n in empty_graph.get_all_nodes() if _is_universe_meta(n)]
    assert len(metas) == 1


def test_resolve_universe_no_match_creates_independent(empty_graph, mock_llm) -> None:
    """未命中字面/别名 → 新建独立 universe（宁裂不并，不靠 LLM 自动并入）。"""
    wp = _make_pipeline(empty_graph, mock_llm)
    wp._resolve_universe("三国演义")
    assert wp._resolve_universe("三国志平话") == "三国志平话"
    metas = [n for n in empty_graph.get_all_nodes() if _is_universe_meta(n)]
    assert len(metas) == 2  # 两个独立 universe，未自动合并


# === 5.5 event 固定现实世界（即使 ingest 作品仍 __reality__） ===


def test_build_event_node_universe_fixed_reality(empty_graph, mock_llm) -> None:
    wp = _make_pipeline(empty_graph, mock_llm)
    ev = wp._build_event_node(
        EventData(name="读演义", content="...", timestamp="2026-07-12T00:00:00")
    )
    assert ev.universe == REALITY_UNIVERSE


# === 5.2 跨 universe 同名不合并（existing_by_name 按 universe 分桶） ===


def test_apply_decisions_cross_universe_same_name_not_merged(
    empty_graph, mock_llm
) -> None:
    """演义"曹操"（三国演义）与正史"曹操"（现实）同名不同 universe：create 同名不并入。"""
    empty_graph.add_node(
        Node(
            id="real_cao",
            name="曹操",
            content="正史",
            node_class=CLASS_CONCEPT,
            universe=REALITY_UNIVERSE,
        )
    )
    wp = _make_pipeline(empty_graph, mock_llm)
    changed = wp._apply_decisions(
        [Decision(action="create", concept=ConceptDraft(name="曹操", content="演义曹操"))],
        universe="三国演义",
    )
    assert len(changed) == 1
    new_node = changed[0]
    assert new_node.universe == "三国演义"
    assert new_node.id != "real_cao"
    # 两个曹操共存（跨 universe 不合并）
    caos = [n for n in empty_graph.get_all_nodes() if n.name == "曹操"]
    assert len(caos) == 2


# === 5.3 跨 universe 事实不互斥（核心收益：修虚构 vs 真实误判互斥） ===


def test_apply_decisions_cross_universe_mutex_rejected(empty_graph, mock_llm) -> None:
    """演义虚构事实与正史记录字面冲突：跨 universe MUST NOT 产互斥。"""
    empty_graph.add_node(
        Node(
            id="real_fact",
            name="曹操借头安众",
            content="正史无此记载",
            node_class=CLASS_FACT,
            universe=REALITY_UNIVERSE,
        )
    )
    wp = _make_pipeline(empty_graph, mock_llm)
    changed = wp._apply_decisions(
        [
            Decision(
                action="create",
                concept=ConceptDraft(
                    name="曹操借头安众", content="演义虚构情节", node_class=CLASS_FACT
                ),
                node_class=CLASS_FACT,
                mutex_with=["real_fact"],  # 指向现实事实 → 跨 universe
            )
        ],
        universe="三国演义",
    )
    new_fact = changed[0]
    # 跨 universe 互斥被拒：两端间无互斥边
    edges = empty_graph.get_edges_between(new_fact.id, "real_fact")
    assert not any(e.type == EDGE_MUTEX for e in edges)


# === 5.4 同 universe 内仍正常互斥 ===


def test_apply_decisions_same_universe_mutex_created(empty_graph, mock_llm) -> None:
    empty_graph.add_node(
        Node(
            id="fact_a",
            name="说法A",
            content="A",
            node_class=CLASS_FACT,
            universe=REALITY_UNIVERSE,
        )
    )
    wp = _make_pipeline(empty_graph, mock_llm)
    changed = wp._apply_decisions(
        [
            Decision(
                action="create",
                concept=ConceptDraft(name="说法B", content="B", node_class=CLASS_FACT),
                node_class=CLASS_FACT,
                mutex_with=["fact_a"],  # 同 universe
            )
        ],
        universe=REALITY_UNIVERSE,
    )
    new_fact = changed[0]
    edges = empty_graph.get_edges_between(new_fact.id, "fact_a")
    assert any(e.type == EDGE_MUTEX for e in edges)

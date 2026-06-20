"""WritePipeline._apply_decisions 测试：3 种 action 类型 + 错误处理。"""

from __future__ import annotations

import pytest

from mcs.core.errors import InvalidDecisionError, UnknownActionError
from mcs.core.plugin_manager import PluginManager
from mcs.core.query_engine import QueryEngine
from mcs.core.store import StoreInterface
from mcs.core.token_budget import TokenBudget
from mcs.core.write_pipeline import WritePipeline
from mcs.entities.decisions import ConceptDraft, Decision
from mcs.entities.graph import Node


def _make_pipeline(store: StoreInterface, mock_llm) -> WritePipeline:
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


def test_create_adds_node_with_edges(empty_graph, mock_llm):
    a = Node(id="anchor1", name="A", content="")
    b = Node(id="anchor2", name="B", content="")
    empty_graph.add_node(a)
    empty_graph.add_node(b)

    wp = _make_pipeline(empty_graph, mock_llm)
    concept = ConceptDraft(name="新概念", content="新内容")
    changed = wp._apply_decisions(
        [
            Decision(
                action="create",
                concept=concept,
                edges_to=[
                    {"target_id": "anchor1"},
                    {"target_id": "anchor2"},
                ],
            )
        ]
    )
    assert len(changed) == 1
    new_node = changed[0]
    assert new_node.name == "新概念"
    # 两个锚点都应该是新节点的事实邻居（事实边两端可达）。
    fact_targets = {e.target_id for e in empty_graph.get_relations(new_node.id)}
    assert fact_targets == {"anchor1", "anchor2"}


def test_create_links_intra_batch_via_edges_to_names(empty_graph, mock_llm):
    """同一批新概念之间用 edges_to_names 按名互连（篇内关系边）。"""
    wp = _make_pipeline(empty_graph, mock_llm)
    changed = wp._apply_decisions(
        [
            Decision(
                action="create",
                concept=ConceptDraft(name="苹果公司", content=""),
                edges_to_names=[
                    {"target_name": "iPhone"},
                    {"target_name": "乔布斯"},
                ],
            ),
            Decision(action="create", concept=ConceptDraft(name="iPhone", content="")),
            Decision(action="create", concept=ConceptDraft(name="乔布斯", content="")),
        ]
    )
    assert [c.name for c in changed] == ["苹果公司", "iPhone", "乔布斯"]
    apple = next(n for n in empty_graph.get_all_nodes() if n.name == "苹果公司")
    fact_targets = {n.name for e in empty_graph.get_relations(apple.id)
                    for n in empty_graph.get_all_nodes()
                    if n.id == e.target_id}
    assert fact_targets == {"iPhone", "乔布斯"}


def test_edges_to_names_skips_unknown_and_self(empty_graph, mock_llm):
    """edges_to_names 引用未知名跳过、引用自身防自环。"""
    wp = _make_pipeline(empty_graph, mock_llm)
    wp._apply_decisions(
        [
            Decision(
                action="create",
                concept=ConceptDraft(name="A", content=""),
                edges_to_names=[
                    {"target_name": "A"},
                    {"target_name": "不存在"},
                    {"target_name": "B"},
                ],
            ),
            Decision(action="create", concept=ConceptDraft(name="B", content="")),
        ]
    )
    a = next(n for n in empty_graph.get_all_nodes() if n.name == "A")
    fact_targets = {n.name for e in empty_graph.get_relations(a.id)
                    for n in empty_graph.get_all_nodes()
                    if n.id == e.target_id}
    assert fact_targets == {"B"}


def test_edges_to_names_can_link_to_merged_target(empty_graph, mock_llm):
    """edges_to_names 指向一个被 merge 的概念名 → 连到其 merge 目标节点。"""
    target = Node(id="t1", name="深度学习", content="")
    empty_graph.add_node(target)
    wp = _make_pipeline(empty_graph, mock_llm)
    wp._apply_decisions(
        [
            Decision(
                action="merge",
                concept=ConceptDraft(name="DL", content=""),
                target_id="t1",
            ),
            Decision(
                action="create",
                concept=ConceptDraft(name="神经网络", content=""),
                edges_to_names=[{"target_name": "DL"}],
            ),
        ]
    )
    nn = next(n for n in empty_graph.get_all_nodes() if n.name == "神经网络")
    fact_targets = {e.target_id for e in empty_graph.get_relations(nn.id)}
    assert "t1" in fact_targets


def test_merge_does_not_add_node(empty_graph, mock_llm):
    target = Node(id="t1", name="Target", content="")
    empty_graph.add_node(target)
    before = len(empty_graph.get_all_nodes())

    wp = _make_pipeline(empty_graph, mock_llm)
    wp._apply_decisions(
        [
            Decision(
                action="merge",
                concept=ConceptDraft(name="newalias", content=""),
                target_id="t1",
            )
        ]
    )
    assert len(empty_graph.get_all_nodes()) == before


def test_merge_adds_aliases_to_target(empty_graph, mock_llm):
    """merge 必须把 aliases_to_add 与 concept.name 真正并入目标别名槽。"""
    target = Node(
        id="t1", name="深度学习", content="", extensions={"alias_index": {"aliases": []}}
    )
    empty_graph.add_node(target)

    wp = _make_pipeline(empty_graph, mock_llm)
    wp._apply_decisions(
        [
            Decision(
                action="merge",
                concept=ConceptDraft(name="deep learning", content=""),
                target_id="t1",
                aliases_to_add=["DL"],
            )
        ]
    )
    aliases = empty_graph.get_node("t1").extensions["alias_index"]["aliases"]
    assert "DL" in aliases
    assert "deep learning" in aliases
    # 不应把等于节点名本身的项当作别名重复写入
    assert "深度学习" not in aliases


def test_merge_appends_concept_content(empty_graph, mock_llm):
    """merge 时 concept.content 应追加到目标节点的 content（子串去重）。"""
    target = Node(id="t1", name="目标", content="已有内容")
    empty_graph.add_node(target)

    wp = _make_pipeline(empty_graph, mock_llm)
    wp._apply_decisions(
        [
            Decision(
                action="merge",
                concept=ConceptDraft(name="x", content="新增事实"),
                target_id="t1",
            )
        ]
    )
    merged = empty_graph.get_node("t1")
    assert "已有内容" in merged.content
    assert "新增事实" in merged.content


def test_merge_without_target_id_raises(empty_graph, mock_llm):
    wp = _make_pipeline(empty_graph, mock_llm)
    with pytest.raises(InvalidDecisionError):
        wp._apply_decisions(
            [
                Decision(
                    action="merge",
                    concept=ConceptDraft(name="X", content=""),
                    target_id=None,
                )
            ]
        )


def test_sanitize_drops_targetless_merge(empty_graph, mock_llm):
    """LLM 偶发的 target_id=null 的 merge 应被清洗丢弃，

    使整次摄入不再因单个坏决策崩溃；create 等正常决策保留。
    """
    wp = _make_pipeline(empty_graph, mock_llm)
    decisions = [
        Decision(
            action="merge",
            concept=ConceptDraft(name="X", content=""),
            target_id=None,
        ),
        Decision(action="create", concept=ConceptDraft(name="好", content="")),
    ]
    cleaned = wp._sanitize_decisions(decisions)
    assert [d.action for d in cleaned] == ["create"]
    # 清洗后应用不再抛 InvalidDecisionError
    changed = wp._apply_decisions(cleaned)
    assert len(changed) == 1
    assert changed[0].name == "好"


def test_no_op_changes_nothing(empty_graph, mock_llm):
    wp = _make_pipeline(empty_graph, mock_llm)
    changed = wp._apply_decisions(
        [Decision(action="no_op", reason="too vague")]
    )
    assert changed == []
    assert empty_graph.get_all_nodes() == []


def test_unknown_action_raises(empty_graph, mock_llm):
    wp = _make_pipeline(empty_graph, mock_llm)
    with pytest.raises(UnknownActionError):
        wp._apply_decisions(
            [Decision(action="delete_planet")]  # type: ignore[arg-type]
        )


def test_multiple_decisions_apply_in_order(empty_graph, mock_llm):
    wp = _make_pipeline(empty_graph, mock_llm)
    changed = wp._apply_decisions(
        [
            Decision(action="create", concept=ConceptDraft(name="A", content="")),
            Decision(action="create", concept=ConceptDraft(name="B", content="")),
            Decision(action="no_op"),
            Decision(action="create", concept=ConceptDraft(name="C", content="")),
        ]
    )
    assert [c.name for c in changed] == ["A", "B", "C"]
    assert len(empty_graph.get_all_nodes()) == 3

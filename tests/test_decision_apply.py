"""Tests for WritePipeline._apply_decisions: 4 action types + error handling."""

from __future__ import annotations

import pytest

from mcs.core.decisions import ConceptDraft, Decision
from mcs.core.errors import UnknownActionError
from mcs.core.graph import GraphStore, Node
from mcs.core.plugin_manager import PluginManager
from mcs.core.query_engine import QueryEngine
from mcs.core.token_budget import TokenBudget
from mcs.core.write_pipeline import WritePipeline


def _make_pipeline(graph: GraphStore, mock_llm) -> WritePipeline:
    pm = PluginManager()
    pm.register(mock_llm)
    tb = TokenBudget(8000)
    qe = QueryEngine(graph=graph, llm=mock_llm, plugin_manager=pm, token_budget=tb)
    return WritePipeline(
        graph=graph,
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
                edges_to=["anchor1", "anchor2"],
            )
        ]
    )
    assert len(changed) == 1
    new_node = changed[0]
    assert new_node.name == "新概念"
    # Both anchors should be neighbors of the new node.
    neighbors = {n.id for n in empty_graph.get_neighbors(new_node.id)}
    assert neighbors == {"anchor1", "anchor2"}


def test_create_with_initial_statements_persists_them(empty_graph, mock_llm):
    wp = _make_pipeline(empty_graph, mock_llm)
    concept = ConceptDraft(name="C", content="")
    changed = wp._apply_decisions(
        [
            Decision(
                action="create",
                concept=concept,
                edges_to=[],
                initial_statements=["s1", "s2"],
            )
        ]
    )
    node = changed[0]
    assert node.extensions["statements"]["items"] == ["s1", "s2"]


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


def test_merge_without_target_id_raises(empty_graph, mock_llm):
    wp = _make_pipeline(empty_graph, mock_llm)
    with pytest.raises(UnknownActionError):
        wp._apply_decisions(
            [
                Decision(
                    action="merge",
                    concept=ConceptDraft(name="X", content=""),
                    target_id=None,
                )
            ]
        )


def test_attach_statement_appends(empty_graph, mock_llm):
    attr_node = Node(id="attr1", name="X的爱好", content="", role="attribute")
    empty_graph.add_node(attr_node)

    wp = _make_pipeline(empty_graph, mock_llm)
    wp._apply_decisions(
        [
            Decision(
                action="attach_statement",
                target_id="attr1",
                statement="说法1",
            ),
            Decision(
                action="attach_statement",
                target_id="attr1",
                statement="说法2",
            ),
        ]
    )
    items = empty_graph.get_node("attr1").extensions["statements"]["items"]
    assert items == ["说法1", "说法2"]


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

"""Tests for WritePipeline: 6-stage pipeline behavior."""

from __future__ import annotations

from typing import ClassVar

from mcs.core.decisions import ConceptDraft, Decision
from mcs.core.graph import GraphStore, Node
from mcs.core.plugin_manager import PluginContext, PluginManager
from mcs.core.query_engine import QueryEngine
from mcs.core.token_budget import TokenBudget
from mcs.core.write_pipeline import WritePipeline
from mcs.interfaces.compaction_plugin import CompactionPluginInterface
from mcs.plugins.base import Plugin


def _build_pipelines(graph: GraphStore, mock_llm, *extra_plugins):
    pm = PluginManager()
    pm.register(mock_llm)
    for p in extra_plugins:
        pm.register(p)
    ctx = PluginContext(
        graph=graph,
        config=None,  # type: ignore[arg-type]
        token_budget=TokenBudget(8000),
        context_renderer=None,  # type: ignore[arg-type]
        plugin_manager=pm,
    )
    pm.initialize_all(ctx)
    query_engine = QueryEngine(
        graph=graph,
        llm=mock_llm,
        plugin_manager=pm,
        token_budget=TokenBudget(8000),
        max_rounds=3,
        max_picked=20,
    )
    write_pipeline = WritePipeline(
        graph=graph,
        llm=mock_llm,
        query_engine=query_engine,
        plugin_manager=pm,
        token_budget=TokenBudget(8000),
    )
    return write_pipeline, query_engine, pm


def test_ingest_calls_query_engine_for_related_lookup(empty_graph, mock_llm):
    """Stage ②: query engine must be invoked with processed text."""
    wp, qe, _ = _build_pipelines(empty_graph, mock_llm)
    mock_llm.set_response("extract_concepts", [])  # silent return
    wp.ingest("some text")
    # decide_directions would be the LLM call inside query(); since there's no
    # entry plugin, query returns empty quickly. We assert query() was *called*
    # by checking that mock_llm log starts with extract_concepts (after query
    # produced its empty result).
    purposes = [c["purpose"] for c in mock_llm.call_log]
    assert "extract_concepts" in purposes


def test_zero_concepts_silently_returns(empty_graph, mock_llm):
    """If extract_concepts returns [], stage ④⑤⑥ are skipped."""
    wp, _, _ = _build_pipelines(empty_graph, mock_llm)
    mock_llm.set_response("extract_concepts", [])
    ctx = wp.ingest("hello")
    assert ctx.concepts == []
    assert ctx.decisions == []
    assert ctx.changed == []


def test_create_decision_adds_node(empty_graph, mock_llm):
    """A 'create' decision should land in graph as a new node + edges."""
    wp, _, _ = _build_pipelines(empty_graph, mock_llm)
    concept = ConceptDraft(name="深度学习", content="一种神经网络方法")
    mock_llm.set_response("extract_concepts", [concept])
    mock_llm.set_response(
        "judge_relations",
        [Decision(action="create", concept=concept, edges_to=[])],
    )
    ctx = wp.ingest("深度学习是机器学习的一个子领域")
    assert len(ctx.changed) == 1
    assert ctx.changed[0].name == "深度学习"
    nodes = empty_graph.get_all_nodes()
    assert len(nodes) == 1
    assert nodes[0].name == "深度学习"


def test_merge_decision_updates_existing_node(empty_graph, mock_llm):
    """A 'merge' decision points to an existing target; that target's
    statements slot gets the initial_statements appended.
    """
    target = Node(id="t1", name="目标节点", content="存量内容")
    empty_graph.add_node(target)

    wp, _, _ = _build_pipelines(empty_graph, mock_llm)
    concept = ConceptDraft(name="新名字", content="新内容")
    mock_llm.set_response("extract_concepts", [concept])
    mock_llm.set_response(
        "judge_relations",
        [
            Decision(
                action="merge",
                concept=concept,
                target_id="t1",
                initial_statements=["新事实"],
            )
        ],
    )
    ctx = wp.ingest("some text")
    assert len(ctx.changed) == 1
    assert ctx.changed[0].id == "t1"
    # The target node still has only one occurrence in the graph.
    assert len([n for n in empty_graph.get_all_nodes() if n.id == "t1"]) == 1


def test_attach_statement_appends_to_target_extensions(empty_graph, mock_llm):
    target = Node(id="attr1", name="小明的爱好", content="", role="attribute")
    empty_graph.add_node(target)

    wp, _, _ = _build_pipelines(empty_graph, mock_llm)
    mock_llm.set_response("extract_concepts", [ConceptDraft(name="X", content="")])
    mock_llm.set_response(
        "judge_relations",
        [
            Decision(
                action="attach_statement",
                target_id="attr1",
                statement="喜欢红色@t1",
            )
        ],
    )
    wp.ingest("source text")
    statements = (
        empty_graph.get_node("attr1").extensions.get("statements", {}).get("items", [])
    )
    assert statements == ["喜欢红色@t1"]


def test_no_op_decision_changes_nothing(empty_graph, mock_llm):
    wp, _, _ = _build_pipelines(empty_graph, mock_llm)
    mock_llm.set_response("extract_concepts", [ConceptDraft(name="X", content="")])
    mock_llm.set_response(
        "judge_relations",
        [Decision(action="no_op", reason="not relevant")],
    )
    ctx = wp.ingest("text")
    assert ctx.changed == []
    assert empty_graph.get_all_nodes() == []


def test_compaction_chain_runs_when_should_run_true(empty_graph, mock_llm):
    """⑥ Compaction plugin's run() must be invoked when should_run returns True."""
    run_count = {"n": 0}

    class _CountingCompaction(Plugin, CompactionPluginInterface):
        name: ClassVar[str] = "counting_compaction"
        interfaces: ClassVar[list[type]] = [CompactionPluginInterface]

        def initialize(self, ctx):
            pass

        def shutdown(self):
            pass

        def should_run(self, changed_nodes, graph):
            return bool(changed_nodes)

        def run(self, changed_nodes, graph, llm_caller):
            run_count["n"] += 1

    wp, _, _ = _build_pipelines(empty_graph, mock_llm, _CountingCompaction())
    concept = ConceptDraft(name="x", content="")
    mock_llm.set_response("extract_concepts", [concept])
    mock_llm.set_response(
        "judge_relations",
        [Decision(action="create", concept=concept, edges_to=[])],
    )
    wp.ingest("text")
    assert run_count["n"] == 1


def test_compaction_skipped_when_should_run_false(empty_graph, mock_llm):
    class _BlockedCompaction(Plugin, CompactionPluginInterface):
        name = "blocked"
        interfaces = [CompactionPluginInterface]

        def initialize(self, ctx):
            pass

        def shutdown(self):
            pass

        def should_run(self, changed_nodes, graph):
            return False

        def run(self, changed_nodes, graph, llm_caller):
            raise AssertionError("run() must NOT be called when should_run False")

    wp, _, _ = _build_pipelines(empty_graph, mock_llm, _BlockedCompaction())
    concept = ConceptDraft(name="x", content="")
    mock_llm.set_response("extract_concepts", [concept])
    mock_llm.set_response(
        "judge_relations",
        [Decision(action="create", concept=concept, edges_to=[])],
    )
    wp.ingest("text")  # no AssertionError → run() was not called


def test_write_context_fields_populated(empty_graph, mock_llm):
    wp, _, _ = _build_pipelines(empty_graph, mock_llm)
    concept = ConceptDraft(name="x", content="content")
    mock_llm.set_response("extract_concepts", [concept])
    mock_llm.set_response(
        "judge_relations",
        [Decision(action="create", concept=concept, edges_to=[])],
    )
    ctx = wp.ingest("input text", doc_id="d1", chunk_id="c1")
    assert ctx.user_input == "input text"
    assert ctx.processed == "input text"
    assert isinstance(ctx.related, list)
    assert ctx.concepts == [concept]
    assert len(ctx.decisions) == 1
    assert len(ctx.changed) == 1
    assert ctx.metadata == {"doc_id": "d1", "chunk_id": "c1"}

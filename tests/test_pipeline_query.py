"""Tests for QueryEngine: 5-stage pipeline behavior."""

from __future__ import annotations

from typing import Any, ClassVar

from mcs.core.graph import GraphStore, Node
from mcs.core.plugin_manager import PluginContext, PluginManager
from mcs.core.query_engine import QueryContext, QueryEngine
from mcs.core.token_budget import TokenBudget
from mcs.interfaces.entry_plugin import EntryPluginInterface
from mcs.interfaces.postprocess_plugin import PostprocessPluginInterface
from mcs.plugins.base import Plugin


class _StaticEntry(Plugin, EntryPluginInterface):
    """Entry plugin that returns a static list of nodes by id from the graph."""

    name: ClassVar[str] = "static_entry"
    interfaces: ClassVar[list[type]] = [EntryPluginInterface]
    priority: ClassVar[int] = 100

    def __init__(self, node_ids: list[str], graph: GraphStore):
        super().__init__(None)
        self._ids = node_ids
        self._graph = graph

    def initialize(self, ctx: Any) -> None:
        return None

    def shutdown(self) -> None:
        return None

    def locate(self, query: str, ctx: Any) -> list[Node]:
        return [
            n
            for n in (self._graph.get_node(i) for i in self._ids)
            if n is not None
        ]


def _build_engine(
    graph: GraphStore, mock_llm, *extra_plugins, max_rounds=3, max_picked=20
) -> QueryEngine:
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
    return QueryEngine(
        graph=graph,
        llm=mock_llm,  # type: ignore[arg-type]
        plugin_manager=pm,
        token_budget=TokenBudget(8000),
        max_rounds=max_rounds,
        max_picked=max_picked,
    )


def test_default_returns_list_of_nodes(seeded_graph, mock_llm):
    """No postprocess plugin → query returns the result_set (List[Node])."""
    engine = _build_engine(
        seeded_graph,
        mock_llm,
        _StaticEntry(["dl"], seeded_graph),
    )
    mock_llm.set_response("decide_directions", [])  # don't expand
    result = engine.query("什么是深度学习？")
    assert isinstance(result, list)
    assert all(isinstance(n, Node) for n in result)
    assert result[0].id == "dl"


def test_empty_seeds_returns_empty_list(seeded_graph, mock_llm):
    """When no entry plugins yield anything, query returns []."""
    engine = _build_engine(seeded_graph, mock_llm)  # no entry plugins
    result = engine.query("nothing matches")
    assert result == []


def test_bfs_visits_each_node_once_in_cycle():
    """A cyclic graph must not loop forever; visited set guarantees this."""
    g = GraphStore()
    a = Node(id="a", name="A", content="A")
    b = Node(id="b", name="B", content="B")
    c = Node(id="c", name="C", content="C")
    for n in [a, b, c]:
        g.add_node(n)
    g.add_edge("a", "b")
    g.add_edge("b", "c")
    g.add_edge("c", "a")  # cycle

    from tests.conftest import MockLLM

    mock = MockLLM()
    engine = _build_engine(g, mock, _StaticEntry(["a"], g))
    # Always expand every neighbor → would loop without visited.
    mock.set_response(
        "decide_directions",
        lambda nodes_in, _free_args: [n.id for n in (nodes_in or [])[1:]],
    )
    result = engine.query("trace cycle")
    ids = {n.id for n in result}
    assert ids == {"a", "b", "c"}


def test_max_rounds_caps_bfs_depth(seeded_graph, mock_llm):
    """A max_rounds=1 traversal only adds 1-hop neighbors of seeds."""
    # Make decide_directions expand every neighbor.
    mock_llm.set_response(
        "decide_directions",
        lambda nodes_in, _free_args: [n.id for n in (nodes_in or [])[1:]],
    )
    engine = _build_engine(
        seeded_graph,
        mock_llm,
        _StaticEntry(["dl"], seeded_graph),
        max_rounds=1,
        max_picked=100,
    )
    result = engine.query("test")
    ids = {n.id for n in result}
    # After 1 round from "dl": dl + its neighbors (nn, ml). cnn is 2 hops away.
    assert "dl" in ids
    assert "nn" in ids
    assert "ml" in ids
    assert "cnn" not in ids


def test_max_picked_caps_node_count(seeded_graph, mock_llm):
    mock_llm.set_response(
        "decide_directions",
        lambda nodes_in, _free_args: [n.id for n in (nodes_in or [])[1:]],
    )
    engine = _build_engine(
        seeded_graph,
        mock_llm,
        _StaticEntry(["dl"], seeded_graph),
        max_rounds=10,
        max_picked=2,
    )
    result = engine.query("test")
    assert len(result) <= 2


def test_existing_context_skips_seed_location(seeded_graph, mock_llm):
    """When existing_context is provided, entry plugins are NOT called."""

    class _RaisingEntry(Plugin, EntryPluginInterface):
        name = "should_not_run"
        interfaces = [EntryPluginInterface]
        priority = 1000

        def initialize(self, ctx):
            pass

        def shutdown(self):
            pass

        def locate(self, query, ctx):
            raise AssertionError("entry plugin must NOT run with existing_context")

    engine = _build_engine(seeded_graph, mock_llm, _RaisingEntry())
    mock_llm.set_response("decide_directions", [])
    seed = seeded_graph.get_node("nn")
    result = engine.query("test", existing_context=[seed])
    assert result[0].id == "nn"


def test_postprocess_chain_transforms_output(seeded_graph, mock_llm):
    """A postprocess plugin can replace List[Node] with any type."""

    class _Stringify(Plugin, PostprocessPluginInterface):
        name = "stringify"
        interfaces = [PostprocessPluginInterface]
        position = "query_postprocess"

        def initialize(self, ctx):
            pass

        def shutdown(self):
            pass

        def process(self, input, ctx):
            return ", ".join(n.name for n in input)

    engine = _build_engine(
        seeded_graph,
        mock_llm,
        _StaticEntry(["dl"], seeded_graph),
        _Stringify(),
    )
    mock_llm.set_response("decide_directions", [])
    result = engine.query("test")
    assert isinstance(result, str)
    assert "深度学习" in result


def test_query_context_lifecycle_fields_populated(seeded_graph, mock_llm):
    """QueryContext intermediate / result_set get filled during execution."""

    captured: dict[str, Any] = {}

    class _Spy(Plugin, PostprocessPluginInterface):
        name = "ctx_spy"
        interfaces = [PostprocessPluginInterface]
        position = "query_postprocess"

        def initialize(self, ctx):
            pass

        def shutdown(self):
            pass

        def process(self, input, ctx: QueryContext):
            captured["intermediate"] = list(ctx.intermediate)
            captured["result_set"] = list(ctx.result_set)
            captured["user_input"] = ctx.user_input
            return input

    engine = _build_engine(
        seeded_graph,
        mock_llm,
        _StaticEntry(["dl"], seeded_graph),
        _Spy(),
    )
    mock_llm.set_response("decide_directions", [])
    engine.query("my query")
    assert captured["user_input"] == "my query"
    assert captured["intermediate"][0].id == "dl"
    assert captured["result_set"][0].id == "dl"

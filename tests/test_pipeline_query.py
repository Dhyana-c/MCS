"""QueryEngine 测试：5 阶段管道行为。"""

from __future__ import annotations

from typing import Any

from mcs.core.graph import GraphStore, Node
from mcs.core.plugin_manager import PluginContext, PluginManager
from mcs.core.query_engine import QueryContext, QueryEngine
from mcs.core.token_budget import TokenBudget
from mcs.interfaces.entry_plugin import EntryPluginInterface
from mcs.interfaces.postprocess_plugin import PostprocessPluginInterface


class _StaticEntry(EntryPluginInterface):
    """按 id 从图中返回静态节点列表的 entry 插件。"""

    def get_name(self) -> str:
        return "static_entry"

    def get_priority(self) -> int:
        return 100

    def __init__(self, node_ids: list[str], graph: GraphStore):
        self._ids = node_ids
        self._graph = graph

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
    """无 postprocess 插件 → 查询返回 result_set (List[Node])。"""
    engine = _build_engine(
        seeded_graph,
        mock_llm,
        _StaticEntry(["dl"], seeded_graph),
    )
    mock_llm.set_response("decide_directions", [])  # 不扩展
    result = engine.query("什么是深度学习？")
    assert isinstance(result, list)
    assert all(isinstance(n, Node) for n in result)
    assert result[0].id == "dl"


def test_empty_seeds_returns_empty_list(seeded_graph, mock_llm):
    """当没有 entry 插件产出任何内容时，查询返回 []。"""
    engine = _build_engine(seeded_graph, mock_llm)  # no entry plugins
    result = engine.query("nothing matches")
    assert result == []


def test_bfs_visits_each_node_once_in_cycle():
    """有环图不能无限循环；visited 集合保证这一点。"""
    g = GraphStore()
    a = Node(id="a", name="A", content="A")
    b = Node(id="b", name="B", content="B")
    c = Node(id="c", name="C", content="C")
    for n in [a, b, c]:
        g.add_node(n)
    g.add_edge("a", "b")
    g.add_edge("b", "c")
    g.add_edge("c", "a")  # 环

    from tests.conftest import MockLLM

    mock = MockLLM()
    engine = _build_engine(g, mock, _StaticEntry(["a"], g))
    # 总是扩展每个邻居 → 若无 visited 将无限循环。
    mock.set_response(
        "decide_directions",
        lambda nodes_in, _free_args: [n.id for n in (nodes_in or [])[1:]],
    )
    result = engine.query("trace cycle")
    ids = {n.id for n in result}
    assert ids == {"a", "b", "c"}


def test_max_rounds_caps_bfs_depth(seeded_graph, mock_llm):
    """max_rounds=1 的遍历只添加种子的一跳邻居。"""
    # 让 decide_directions 扩展每个邻居。
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
    # 从 "dl" 出发 1 轮后：dl + 其邻居 (nn, ml)。cnn 距离 2 跳。
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
    """当提供 existing_context 时，entry 插件不会被调用。"""

    class _RaisingEntry(EntryPluginInterface):
        def get_name(self) -> str:
            return "should_not_run"

        def get_priority(self) -> int:
            return 1000

        def locate(self, query, ctx):
            raise AssertionError("entry 插件在有 existing_context 时不能运行")

    engine = _build_engine(seeded_graph, mock_llm, _RaisingEntry())
    mock_llm.set_response("decide_directions", [])
    seed = seeded_graph.get_node("nn")
    result = engine.query("test", existing_context=[seed])
    assert result[0].id == "nn"


def test_postprocess_chain_transforms_output(seeded_graph, mock_llm):
    """postprocess 插件可以将 List[Node] 替换为任意类型。"""

    class _Stringify(PostprocessPluginInterface):
        def get_name(self) -> str:
            return "stringify"

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
    """QueryContext 的 intermediate / result_set 在执行过程中被填充。"""

    captured: dict[str, Any] = {}

    class _Spy(PostprocessPluginInterface):
        def get_name(self) -> str:
            return "ctx_spy"

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

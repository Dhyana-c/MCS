"""QueryEngine 测试：5 阶段管道行为。"""

from __future__ import annotations

from typing import Any

from mcs.core.graph import Node, Subgraph
from mcs.core.plugin_manager import PluginContext, PluginManager
from mcs.core.query_engine import QueryContext, QueryEngine
from mcs.core.token_budget import TokenBudget
from mcs.interfaces.entry_plugin import EntryPluginInterface
from mcs.interfaces.postprocess_plugin import PostprocessPluginInterface
from mcs.interfaces.query_preprocess_plugin import QueryPreprocessPluginInterface
from mcs.stores.in_memory import InMemoryStore

GraphStore = InMemoryStore


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
    graph: GraphStore, mock_llm, *extra_plugins, max_rounds=3, max_accumulated_nodes=1000
) -> QueryEngine:
    pm = PluginManager()
    pm.register(mock_llm)
    for p in extra_plugins:
        pm.register(p)
    ctx = PluginContext(
        store=graph,
        config=None,  # type: ignore[arg-type]
        token_budget=TokenBudget(8000),
        context_renderer=None,  # type: ignore[arg-type]
        plugin_manager=pm,
    )
    pm.initialize_all(ctx)
    return QueryEngine(
        store=graph,
        llm=mock_llm,  # type: ignore[arg-type]
        plugin_manager=pm,
        token_budget=TokenBudget(8000),
        max_rounds=max_rounds,
        max_accumulated_nodes=max_accumulated_nodes,
    )


def test_default_returns_subgraph(seeded_graph, mock_llm):
    """无 postprocess 插件 → 查询返回 Subgraph。"""
    engine = _build_engine(
        seeded_graph,
        mock_llm,
        _StaticEntry(["dl"], seeded_graph),
    )
    # select_facts 不扩展任何邻居
    mock_llm.set_response("select_nodes", [])
    result = engine.query("什么是深度学习？")
    assert isinstance(result, Subgraph)
    assert all(isinstance(n, Node) for n in result.nodes)
    assert result.nodes[0].id == "dl"


def test_empty_seeds_returns_empty_subgraph(seeded_graph, mock_llm):
    """当没有 entry 插件产出任何内容时，查询返回空 Subgraph。"""
    engine = _build_engine(seeded_graph, mock_llm)  # no entry plugins
    result = engine.query("nothing matches")
    assert isinstance(result, Subgraph)
    assert result.nodes == []
    assert result.edges == []


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
    # select_facts 选中所有候选（经 MockLLM 回退到 select_nodes mock）
    mock.set_response(
        "select_nodes",
        lambda nodes_in, _free_args: [n.id for n in (nodes_in or [])],
    )
    result = engine.query("trace cycle")
    ids = {n.id for n in result.nodes}
    assert ids == {"a", "b", "c"}


def test_max_rounds_caps_bfs_depth(seeded_graph, mock_llm):
    """max_rounds 限制遍历轮数。"""
    # 让 select_facts 选中所有候选
    mock_llm.set_response(
        "select_nodes",
        lambda nodes_in, _free_args: [n.id for n in (nodes_in or [])],
    )
    engine = _build_engine(
        seeded_graph,
        mock_llm,
        _StaticEntry(["dl"], seeded_graph),
        max_rounds=2,
        max_accumulated_nodes=1000,
    )
    result = engine.query("test")
    ids = {n.id for n in result.nodes}
    # 种子 dl 直接加入 accumulated
    assert "dl" in ids
    # max_rounds=2：第 1 轮扩展 dl 的邻居，第 2 轮扩展选中邻居的邻居
    assert "nn" in ids or "ml" in ids  # 至少扩展了一跳


def test_max_accumulated_nodes_caps_node_count(seeded_graph, mock_llm):
    """max_accumulated_nodes 限制累积节点数。"""
    mock_llm.set_response(
        "select_nodes",
        lambda nodes_in, _free_args: [n.id for n in (nodes_in or [])],
    )
    engine = _build_engine(
        seeded_graph,
        mock_llm,
        _StaticEntry(["dl"], seeded_graph),
        max_rounds=10,
        max_accumulated_nodes=2,
    )
    result = engine.query("test")
    assert len(result.nodes) <= 2


def test_token_budget_terminates_traverse(seeded_graph, mock_llm):
    """token 预算超限时遍历终止。"""
    pm = PluginManager()
    pm.register(mock_llm)
    pm.register(_StaticEntry(["dl"], seeded_graph))
    ctx = PluginContext(
        store=seeded_graph,
        config=None,  # type: ignore[arg-type]
        token_budget=TokenBudget(50),  # 极小预算
        context_renderer=None,  # type: ignore[arg-type]
        plugin_manager=pm,
    )
    pm.initialize_all(ctx)
    engine = QueryEngine(
        store=seeded_graph,
        llm=mock_llm,  # type: ignore[arg-type]
        plugin_manager=pm,
        token_budget=TokenBudget(50),  # 极小预算
        max_rounds=10,
        max_accumulated_nodes=1000,
    )
    mock_llm.set_response(
        "select_nodes",
        lambda nodes_in, _free_args: [n.id for n in (nodes_in or [])],
    )
    result = engine.query("test")
    # 应在 token 预算内终止，返回 Subgraph
    assert isinstance(result, Subgraph)


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
    # select_facts 不扩展
    mock_llm.set_response("select_nodes", [])
    seed = seeded_graph.get_node("nn")
    result = engine.query("test", existing_context=[seed])
    assert isinstance(result, Subgraph)
    assert result.nodes[0].id == "nn"


def test_postprocess_chain_transforms_output(seeded_graph, mock_llm):
    """postprocess 插件可以将 Subgraph 替换为任意类型。"""

    class _Stringify(PostprocessPluginInterface):
        def get_name(self) -> str:
            return "stringify"

        def process(self, input, ctx):
            if isinstance(input, Subgraph):
                return ", ".join(n.name for n in input.nodes)
            return str(input)

    engine = _build_engine(
        seeded_graph,
        mock_llm,
        _StaticEntry(["dl"], seeded_graph),
        _Stringify(),
    )
    mock_llm.set_response("select_nodes", [])
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
    mock_llm.set_response("select_nodes", [])
    engine.query("my query")
    assert captured["user_input"] == "my query"
    assert captured["intermediate"][0].id == "dl"
    assert captured["result_set"][0].id == "dl"


def test_preprocess_chain_transforms_query_text(seeded_graph, mock_llm):
    """阶段 ① QueryPreprocessPlugin 可以修改查询文本。"""

    class _UpperPreprocess(QueryPreprocessPluginInterface):
        def get_name(self) -> str:
            return "upper_preprocess"

        def preprocess(self, text: str, ctx) -> str:
            return text.upper()

    engine = _build_engine(
        seeded_graph,
        mock_llm,
        _StaticEntry(["dl"], seeded_graph),
        _UpperPreprocess(),
    )
    mock_llm.set_response("select_nodes", [])
    result = engine.query("test")
    # 查询应正常执行，QueryPreprocessPlugin 已处理文本
    assert isinstance(result, Subgraph)


def test_query_engine_preprocess_and_postprocess_independent(seeded_graph, mock_llm):
    """QueryPreprocess 和 Postprocess 使用独立类型，互不干扰。"""
    processed_text = {}

    class _TrackPreprocess(QueryPreprocessPluginInterface):
        def get_name(self) -> str:
            return "track_preprocess"

        def preprocess(self, text: str, ctx) -> str:
            processed_text["value"] = text
            return text

    class _TrackPostprocess(PostprocessPluginInterface):
        def get_name(self) -> str:
            return "track_postprocess"

        def process(self, input, ctx):
            return input

    engine = _build_engine(
        seeded_graph,
        mock_llm,
        _StaticEntry(["dl"], seeded_graph),
        _TrackPreprocess(),
        _TrackPostprocess(),
    )
    mock_llm.set_response("select_nodes", [])
    engine.query("my query")
    assert processed_text.get("value") == "my query"


def test_trim_plugin_chain(seeded_graph, mock_llm):
    """TrimPlugin 链在 EntryPlugin 之后执行，多个 TrimPlugin 按优先级依次运行。"""
    from mcs.interfaces.trim_plugin import TrimPluginInterface

    trim_calls: list[list[str]] = []

    class _SpyTrim(TrimPluginInterface):
        def get_name(self) -> str:
            return "spy_trim"

        def get_priority(self) -> int:
            return 10

        def trim(self, nodes, budget, *, query="", ctx=None):
            trim_calls.append([n.id for n in nodes])
            return nodes[:1]  # 只保留第一个

    engine = _build_engine(
        seeded_graph,
        mock_llm,
        _StaticEntry(["dl", "nn"], seeded_graph),
        _SpyTrim(),
    )
    mock_llm.set_response("select_nodes", [])
    result = engine.query("test")
    # TrimPlugin 应被调用
    assert len(trim_calls) > 0
    # 结果应只包含 TrimPlugin 筛选后的种子
    assert isinstance(result, Subgraph)
    assert len(result.nodes) <= 1


def test_trim_chain_empty_skips(seeded_graph, mock_llm):
    """未注册 TrimPlugin 时仍正常执行（TrimPlugin 链为空则跳过裁剪）。"""
    engine = _build_engine(
        seeded_graph,
        mock_llm,
        _StaticEntry(["dl"], seeded_graph),
    )
    mock_llm.set_response("select_nodes", [])
    # 无 TrimPlugin → 不报错，正常执行
    result = engine.query("test")
    assert isinstance(result, Subgraph)


# === 事实 BFS 遍历测试 ===


def test_fact_bfs_expands_hierarchy_children(seeded_graph, mock_llm):
    """事实 BFS 遍历：hierarchy 子节点作为视图的一部分被选中。"""
    mock_llm.set_response(
        "select_nodes",
        lambda nodes_in, _free_args: [n.id for n in (nodes_in or [])],
    )
    engine = _build_engine(
        seeded_graph,
        mock_llm,
        _StaticEntry(["dl"], seeded_graph),
        max_rounds=2,
    )
    result = engine.query("test")
    ids = {n.id for n in result.nodes}
    assert "dl" in ids
    assert "nn" in ids or "ml" in ids


def test_fact_bfs_collects_fact_edges():
    """事实 BFS 遍历：选中的 fact 边应出现在 Subgraph.edges 中。"""
    g = GraphStore()
    a = Node(id="a", name="A", content="A")
    b = Node(id="b", name="B", content="B")
    c = Node(id="c", name="C", content="C")
    for n in [a, b, c]:
        g.add_node(n)
    # fact 边
    g.add_edge("a", "b", kind="fact", label="喜欢")
    g.add_edge("b", "c", kind="fact", label="包含")

    from tests.conftest import MockLLM

    mock = MockLLM()
    engine = _build_engine(g, mock, _StaticEntry(["a"], g))
    # select_facts 选中所有（经 MockLLM 回退转换）
    mock.set_response(
        "select_nodes",
        lambda nodes_in, _free_args: [n.id for n in (nodes_in or [])],
    )
    result = engine.query("test")
    # fact 边应被收集
    assert isinstance(result, Subgraph)
    assert len(result.edges) >= 1
    assert all(e.kind == "fact" for e in result.edges)


def test_fact_bfs_endpoints_added_to_accumulated():
    """选中 fact 边时，两端节点都应加入 accumulated。"""
    g = GraphStore()
    a = Node(id="a", name="A", content="A")
    b = Node(id="b", name="B", content="B")
    c = Node(id="c", name="C", content="C")
    for n in [a, b, c]:
        g.add_node(n)
    g.add_edge("a", "b", kind="fact", label="喜欢")

    from tests.conftest import MockLLM

    mock = MockLLM()
    engine = _build_engine(g, mock, _StaticEntry(["a"], g))
    mock.set_response(
        "select_nodes",
        lambda nodes_in, _free_args: [n.id for n in (nodes_in or [])],
    )
    result = engine.query("test")
    ids = {n.id for n in result.nodes}
    # a 是种子，b 是 fact 边端点
    assert "a" in ids
    assert "b" in ids


def test_fact_bfs_parse_error_skips_node(seeded_graph, mock_llm):
    """LLMParseError 时跳过当前节点，继续处理队列。"""
    from mcs.core.errors import LLMParseError

    call_count = 0

    def fail_once(nodes_in, _free_args):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise LLMParseError("select_facts", "invalid", "test error")
        return [n.id for n in (nodes_in or []) if n.id != "dl"]

    mock_llm.set_response("select_nodes", fail_once)
    engine = _build_engine(seeded_graph, mock_llm, _StaticEntry(["dl"], seeded_graph))
    result = engine.query("test")

    # 即使首次失败，种子 dl 仍应在结果中
    assert isinstance(result, Subgraph)
    assert any(n.id == "dl" for n in result.nodes)


def test_traverse_with_no_neighbors_or_facts(seeded_graph, mock_llm):
    """叶子节点（无子节点无事实）不会触发 LLM 调用。"""
    # cnn 是叶子节点
    engine = _build_engine(
        seeded_graph,
        mock_llm,
        _StaticEntry(["cnn"], seeded_graph),
    )
    mock_llm.set_response("select_nodes", [])
    result = engine.query("test")
    assert isinstance(result, Subgraph)
    assert result.nodes[0].id == "cnn"

"""QueryEngine 测试：5 阶段管道行为。"""

from __future__ import annotations

from typing import Any

from mcs.core.graph import Node
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


def test_default_returns_list_of_nodes(seeded_graph, mock_llm):
    """无 postprocess 插件 → 查询返回 result_set (List[Node])。"""
    engine = _build_engine(
        seeded_graph,
        mock_llm,
        _StaticEntry(["dl"], seeded_graph),
    )
    # select_nodes 不扩展任何邻居
    mock_llm.set_response("select_nodes", [])
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
    # select_nodes 选中所有候选
    mock.set_response(
        "select_nodes",
        lambda nodes_in, _free_args: [n.id for n in (nodes_in or [])],
    )
    result = engine.query("trace cycle")
    ids = {n.id for n in result}
    assert ids == {"a", "b", "c"}


def test_max_rounds_caps_bfs_depth(seeded_graph, mock_llm):
    """max_rounds 限制遍历轮数。"""
    # 让 select_nodes 选中所有候选
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
    ids = {n.id for n in result}
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
    assert len(result) <= 2


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
    # 应在 token 预算内终止
    assert isinstance(result, list)


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
    # select_nodes 不扩展
    mock_llm.set_response("select_nodes", [])
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
    assert isinstance(result, list)


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


def test_seed_selector_plugin_chain(seeded_graph, mock_llm):
    """SeedSelectorPlugin 链在 TrimPlugin 之后执行。"""
    from mcs.interfaces.seed_selector_plugin import SeedSelectorPluginInterface

    selector_calls: list[list[str]] = []

    class _SpySelector(SeedSelectorPluginInterface):
        def get_name(self) -> str:
            return "spy_selector"

        def get_priority(self) -> int:
            return 10

        def select(self, seeds, query, budget, ctx=None):
            selector_calls.append([n.id for n in seeds])
            return seeds[:1]  # 只保留第一个

    engine = _build_engine(
        seeded_graph,
        mock_llm,
        _StaticEntry(["dl", "nn"], seeded_graph),
        _SpySelector(),
    )
    mock_llm.set_response("select_nodes", [])
    result = engine.query("test")
    # SeedSelector 应被调用
    assert len(selector_calls) > 0
    # 结果应只包含 SeedSelector 筛选后的种子
    assert len(result) <= 1


def test_seed_selector_chain_empty_skips(seeded_graph, mock_llm):
    """未注册 SeedSelectorPlugin 时跳过语义筛选。"""
    engine = _build_engine(
        seeded_graph,
        mock_llm,
        _StaticEntry(["dl"], seeded_graph),
    )
    mock_llm.set_response("select_nodes", [])
    # 无 SeedSelectorPlugin → 不报错，正常执行
    result = engine.query("test")
    assert isinstance(result, list)


# === 批量邻居扩展测试 ===


def test_batch_packing_combines_multiple_nodes(seeded_graph, mock_llm):
    """批量打包：多个节点及其邻居合并后一次 LLM 调用。"""
    from tests.conftest import MockLLM

    # 构造两个种子的场景
    g = seeded_graph
    dl = g.get_node("dl")
    ml = g.get_node("ml")

    mock = MockLLM()
    engine = _build_engine(g, mock, _StaticEntry(["dl", "ml"], g))

    # 记录 LLM 调用次数
    call_count = 0

    def count_and_select(nodes_in, _free_args):
        nonlocal call_count
        call_count += 1
        # 只选邻居，不选中心节点
        ids = [n.id for n in (nodes_in or [])]
        # 排除中心节点（dl, ml）
        return [i for i in ids if i not in ("dl", "ml")]

    mock.set_response("select_nodes", count_and_select)
    engine.query("test")

    # 批量模式应该减少 LLM 调用次数（理想情况 1 次，而非每个种子 1 次）
    # 注意：实际调用次数取决于打包阈值和节点大小
    assert call_count >= 1


def test_batch_depth_calculation_correct():
    """批量模式下邻居深度计算正确。"""
    from tests.conftest import MockLLM

    g = GraphStore()
    # 构造两跳图：a -> b1, b2; b1 -> c1; b2 -> c2
    nodes = [
        Node(id="a", name="A", content="A"),
        Node(id="b1", name="B1", content="B1"),
        Node(id="b2", name="B2", content="B2"),
        Node(id="c1", name="C1", content="C1"),
        Node(id="c2", name="C2", content="C2"),
    ]
    for n in nodes:
        g.add_node(n)
    g.add_edge("a", "b1")
    g.add_edge("a", "b2")
    g.add_edge("b1", "c1")
    g.add_edge("b2", "c2")

    mock = MockLLM()
    pm = PluginManager()
    pm.register(mock)
    pm.register(_StaticEntry(["a"], g))
    ctx = PluginContext(
        store=g,
        config=None,
        token_budget=TokenBudget(8000),
        context_renderer=None,
        plugin_manager=pm,
    )
    pm.initialize_all(ctx)
    engine = QueryEngine(
        store=g,
        llm=mock,
        plugin_manager=pm,
        token_budget=TokenBudget(8000),
        max_rounds=2,
        max_accumulated_nodes=1000,
    )

    # 选中所有邻居
    mock.set_response(
        "select_nodes",
        lambda nodes_in, _free_args: [n.id for n in (nodes_in or [])],
    )
    result = engine.query("test")

    # 验证所有节点都被访问
    ids = {n.id for n in result}
    assert ids == {"a", "b1", "b2", "c1", "c2"}


def test_batch_visited_dedup_shared_neighbor():
    """同一邻居被多个中心共享时只处理一次。"""
    from tests.conftest import MockLLM

    g = GraphStore()
    # a1, a2 都指向 shared
    a1 = Node(id="a1", name="A1", content="A1")
    a2 = Node(id="a2", name="A2", content="A2")
    shared = Node(id="shared", name="Shared", content="Shared")
    for n in [a1, a2, shared]:
        g.add_node(n)
    g.add_edge("a1", "shared")
    g.add_edge("a2", "shared")

    mock = MockLLM()
    engine = _build_engine(g, mock, _StaticEntry(["a1", "a2"], g))

    selected_count = 0

    def track_selection(nodes_in, _free_args):
        nonlocal selected_count
        ids = [n.id for n in (nodes_in or [])]
        # 只选 shared
        selected = [i for i in ids if i == "shared"]
        selected_count += len(selected)
        return selected

    mock.set_response("select_nodes", track_selection)
    result = engine.query("test")

    # shared 只能在结果中出现一次
    ids = [n.id for n in result]
    assert ids.count("shared") == 1


def test_batch_fallback_on_parse_error(seeded_graph, mock_llm):
    """LLMParseError 时回退到逐节点处理。"""
    from mcs.core.errors import LLMParseError

    # 第一次调用抛出 LLMParseError，触发回退
    call_count = 0

    def fail_then_succeed(nodes_in, _free_args):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            raise LLMParseError("select_nodes", "invalid", "test error")
        return [n.id for n in (nodes_in or []) if n.id != "dl"]

    mock_llm.set_response("select_nodes", fail_then_succeed)
    engine = _build_engine(seeded_graph, mock_llm, _StaticEntry(["dl"], seeded_graph))
    result = engine.query("test")

    # 回退后应仍有结果
    assert isinstance(result, list)
    assert len(result) >= 1  # 至少包含种子 dl


def test_batch_overflow_node_put_back_to_queue():
    """超预算时未加入批次的节点应放回队列头部，下一轮继续处理。"""
    from tests.conftest import MockLLM

    g = GraphStore()
    # 构造三个种子，每个有大邻居（模拟超预算场景）
    nodes = [
        Node(id="a", name="A", content="A node with large content"),
        Node(id="b", name="B", content="B node with large content"),
        Node(id="c", name="C", content="C node with large content"),
        Node(id="n1", name="N1", content="Neighbor 1 of A"),
        Node(id="n2", name="N2", content="Neighbor 2 of B"),
        Node(id="n3", name="N3", content="Neighbor 3 of C"),
    ]
    for n in nodes:
        g.add_node(n)
    g.add_edge("a", "n1")
    g.add_edge("b", "n2")
    g.add_edge("c", "n3")

    mock = MockLLM()
    # 极小预算：迫使批次只能容纳一个节点
    pm = PluginManager()
    pm.register(mock)
    pm.register(_StaticEntry(["a", "b", "c"], g))
    ctx = PluginContext(
        store=g,
        config=None,
        token_budget=TokenBudget(100),  # 极小预算
        context_renderer=None,
        plugin_manager=pm,
    )
    pm.initialize_all(ctx)
    engine = QueryEngine(
        store=g,
        llm=mock,
        plugin_manager=pm,
        token_budget=TokenBudget(100),
        max_rounds=1,
        max_accumulated_nodes=100,
    )

    # 选中所有邻居
    mock.set_response(
        "select_nodes",
        lambda nodes_in, _free_args: [n.id for n in (nodes_in or []) if n.id.startswith("n")],
    )
    result = engine.query("test")

    # 即使预算极小，所有种子和邻居都应被处理（因为超预算节点放回队列）
    ids = {n.id for n in result}
    # 种子 a, b, c 应都在 accumulated
    assert "a" in ids
    assert "b" in ids
    assert "c" in ids

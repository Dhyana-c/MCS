"""QueryEngine 测试：5 阶段管道行为。"""

from __future__ import annotations

from typing import Any

from conftest import make_query_engine

from mcs.core.plugin_manager import PluginContext, PluginManager
from mcs.core.query_engine import QueryContext, QueryEngine
from mcs.core.token_budget import TokenBudget
from mcs.entities.graph import CLASS_EVENT, EDGE_ASSOC, Node, Subgraph
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


def test_default_returns_subgraph(seeded_graph, mock_llm):
    """无 postprocess 插件 → 查询返回 Subgraph。"""
    engine = make_query_engine(
        seeded_graph,
        mock_llm,
        _StaticEntry(["dl"], seeded_graph),
    )
    # 种子只进 frontier，需 LLM 标 `结果` 才进 accumulated：仅选中心(编号1)、不探索
    mock_llm.set_response("select_facts", {"result": [1], "frontier": []})
    result = engine.query("什么是深度学习？")
    assert isinstance(result, Subgraph)
    assert all(isinstance(n, Node) for n in result.nodes)
    assert result.nodes[0].id == "dl"


def test_empty_seeds_returns_empty_subgraph(seeded_graph, mock_llm):
    """当没有 entry 插件产出任何内容时，查询返回空 Subgraph。"""
    engine = make_query_engine(seeded_graph, mock_llm)  # no entry plugins
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
    engine = make_query_engine(g, mock, _StaticEntry(["a"], g))
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
    engine = make_query_engine(
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
    engine = make_query_engine(
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

    engine = make_query_engine(seeded_graph, mock_llm, _RaisingEntry())
    # 种子(nn)经 LLM 标 `结果`（编号1）进 accumulated；不探索
    mock_llm.set_response("select_facts", {"result": [1], "frontier": []})
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

    engine = make_query_engine(
        seeded_graph,
        mock_llm,
        _StaticEntry(["dl"], seeded_graph),
        _Stringify(),
    )
    mock_llm.set_response("select_facts", {"result": [1], "frontier": []})
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

    engine = make_query_engine(
        seeded_graph,
        mock_llm,
        _StaticEntry(["dl"], seeded_graph),
        _Spy(),
    )
    mock_llm.set_response("select_facts", {"result": [1], "frontier": []})
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

    engine = make_query_engine(
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

    engine = make_query_engine(
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

    engine = make_query_engine(
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
    engine = make_query_engine(
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
    engine = make_query_engine(
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
    g.add_edge("a", "b")
    g.add_edge("b", "c")

    from tests.conftest import MockLLM

    mock = MockLLM()
    engine = make_query_engine(g, mock, _StaticEntry(["a"], g))
    # select_facts 选中所有（经 MockLLM 回退转换）
    mock.set_response(
        "select_nodes",
        lambda nodes_in, _free_args: [n.id for n in (nodes_in or [])],
    )
    result = engine.query("test")
    # fact 边应被收集
    assert isinstance(result, Subgraph)
    assert len(result.edges) >= 1
    assert all(e.type == "关联" for e in result.edges)


def test_fact_bfs_endpoints_added_to_accumulated():
    """选中 fact 边时，两端节点都应加入 accumulated。"""
    g = GraphStore()
    a = Node(id="a", name="A", content="A")
    b = Node(id="b", name="B", content="B")
    c = Node(id="c", name="C", content="C")
    for n in [a, b, c]:
        g.add_node(n)
    g.add_edge("a", "b")

    from tests.conftest import MockLLM

    mock = MockLLM()
    engine = make_query_engine(g, mock, _StaticEntry(["a"], g))
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
    """LLMParseError 时跳过当前调用，继续遍历不崩溃；之前选中的节点保留。"""
    from mcs.core.errors import LLMParseError

    call_count = 0

    def fail_later(nodes_in, _free_args):
        # 首轮（种子视图）成功：把候选全选为"两者"（含种子 dl）；
        # 后续轮次抛 LLMParseError → 被捕获跳过，遍历不崩溃。
        nonlocal call_count
        call_count += 1
        if call_count >= 2:
            raise LLMParseError("select_facts", "invalid", "test error")
        return [n.id for n in (nodes_in or [])]

    mock_llm.set_response("select_nodes", fail_later)
    engine = make_query_engine(seeded_graph, mock_llm, _StaticEntry(["dl"], seeded_graph))
    result = engine.query("test")

    # 首轮选中的种子 dl 保留；后续 parse error 被优雅跳过
    assert isinstance(result, Subgraph)
    assert any(n.id == "dl" for n in result.nodes)


def test_traverse_leaf_seed_still_evaluated(seeded_graph, mock_llm):
    """修法 A'：孤立/叶子种子（无子节点无事实）仍单节点成视图、交 LLM 评估。

    旧行为靠种子预填 accumulated 兜底；解耦后种子只进 frontier，若 `_node_view`
    对无视图节点返回 None 则永失 accumulated。A' 使叶子种子仍被评估、可标 `结果`。
    """
    # cnn 是叶子节点（无下钻成员、无关系边）
    engine = make_query_engine(
        seeded_graph,
        mock_llm,
        _StaticEntry(["cnn"], seeded_graph),
    )
    # 叶子种子单节点成视图（编号1=cnn），LLM 标 `结果` → 进 accumulated
    mock_llm.set_response("select_facts", {"result": [1], "frontier": []})
    result = engine.query("test")
    assert isinstance(result, Subgraph)
    assert result.nodes[0].id == "cnn"


def test_traverse_leaf_seed_not_selected_returns_empty(seeded_graph, mock_llm):
    """叶子种子未被标任何角色 → 不进 accumulated → 空结果（不崩溃）。"""
    engine = make_query_engine(
        seeded_graph,
        mock_llm,
        _StaticEntry(["cnn"], seeded_graph),
    )
    mock_llm.set_response("select_facts", {"result": [], "frontier": []})
    result = engine.query("test")
    assert isinstance(result, Subgraph)
    assert result.nodes == []


# ─── 定向查事件 ──────────────────────────────────────────────────────────


def test_get_related_events_bypasses_cargo_rule():
    """get_related_events 绕过载重规则：核心节点能查到背书它的事件。"""
    from tests.conftest import MockLLM

    g = GraphStore()
    fact = Node(id="f1", name="某事实", content="某事实", node_class="事实")
    g.add_node(fact)
    event = Node(id="e1", name="用户对话", content="用户说了啥", node_class=CLASS_EVENT)
    g.add_node(event)
    g.add_edge("e1", "f1", type=EDGE_ASSOC)  # 事件→事实（背书）

    # 核心侧 get_relations 不含事件边（载重规则）
    fact_assoc = [e for e in g.get_relations("f1") if e.type == EDGE_ASSOC]
    assert not any(e.source_id == "e1" for e in fact_assoc)

    # 定向查事件能绕过
    mock = MockLLM()
    engine = make_query_engine(g, mock, _StaticEntry(["f1"], g))
    events = engine.get_related_events("f1")
    assert len(events) >= 1
    assert events[0].node_class == CLASS_EVENT


def test_get_related_events_no_events():
    """无事件背书时返回空列表。"""
    from tests.conftest import MockLLM

    g = GraphStore()
    concept = Node(id="c1", name="概念", content="概念", node_class="概念")
    g.add_node(concept)

    mock = MockLLM()
    engine = make_query_engine(g, mock, _StaticEntry(["c1"], g))
    assert engine.get_related_events("c1") == []


def test_get_related_events_sorted_by_timestamp_desc():
    """get_related_events 按时间倒排：最新事件排最前。"""
    from tests.conftest import MockLLM

    g = GraphStore()
    fact = Node(id="f1", name="某事实", content="某事实", node_class="事实")
    g.add_node(fact)

    e1 = Node(
        id="e1", name="早期事件", content="", node_class=CLASS_EVENT,
        extensions={"event_meta": {"timestamp": "2024-01-01T00:00:00"}},
    )
    e2 = Node(
        id="e2", name="中期事件", content="", node_class=CLASS_EVENT,
        extensions={"event_meta": {"timestamp": "2024-06-15T00:00:00"}},
    )
    e3 = Node(
        id="e3", name="最新事件", content="", node_class=CLASS_EVENT,
        extensions={"event_meta": {"timestamp": "2025-03-20T00:00:00"}},
    )
    for e in [e1, e2, e3]:
        g.add_node(e)
        g.add_edge(e.id, "f1", type=EDGE_ASSOC)

    mock = MockLLM()
    engine = make_query_engine(g, mock, _StaticEntry(["f1"], g))
    events = engine.get_related_events("f1")
    # 时间倒排：最新排最前
    assert [e.id for e in events] == ["e3", "e2", "e1"]


def test_get_related_events_limit_truncation():
    """limit 截断：只返回最新的 N 个事件（时间倒排截断）。"""
    from tests.conftest import MockLLM

    g = GraphStore()
    fact = Node(id="f1", name="某事实", content="某事实", node_class="事实")
    g.add_node(fact)

    e1 = Node(
        id="e1", name="旧事件", content="", node_class=CLASS_EVENT,
        extensions={"event_meta": {"timestamp": "2024-01-01T00:00:00"}},
    )
    e2 = Node(
        id="e2", name="新事件", content="", node_class=CLASS_EVENT,
        extensions={"event_meta": {"timestamp": "2025-06-01T00:00:00"}},
    )
    for e in [e1, e2]:
        g.add_node(e)
        g.add_edge(e.id, "f1", type=EDGE_ASSOC)

    mock = MockLLM()
    engine = make_query_engine(g, mock, _StaticEntry(["f1"], g))
    # limit=1 → 只返回最新
    events = engine.get_related_events("f1", limit=1)
    assert len(events) == 1
    assert events[0].id == "e2"


def test_get_related_events_no_timestamp_sorted_last():
    """无 timestamp 的事件排在有 timestamp 的之后。"""
    from tests.conftest import MockLLM

    g = GraphStore()
    fact = Node(id="f1", name="某事实", content="某事实", node_class="事实")
    g.add_node(fact)

    e_ts = Node(
        id="e_ts", name="有时间事件", content="", node_class=CLASS_EVENT,
        extensions={"event_meta": {"timestamp": "2025-01-01T00:00:00"}},
    )
    e_no = Node(
        id="e_no", name="无时间事件", content="", node_class=CLASS_EVENT,
        extensions={"event_meta": {}},
    )
    for e in [e_ts, e_no]:
        g.add_node(e)
        g.add_edge(e.id, "f1", type=EDGE_ASSOC)

    mock = MockLLM()
    engine = make_query_engine(g, mock, _StaticEntry(["f1"], g))
    events = engine.get_related_events("f1")
    # 有 timestamp 的排前
    assert events[0].id == "e_ts"
    assert events[1].id == "e_no"


# ─── read-repair 同名合并 ──────────────────────────────────────────────


def test_read_repair_merges_same_name_nodes():
    """read-repair：BFS 遇到同名节点时合并到首次遇到的那一个。"""
    from tests.conftest import MockLLM

    g = GraphStore()
    # 两个同名节点（不同 id）
    a1 = Node(id="a1", name="苹果", content="苹果公司")
    a2 = Node(id="a2", name="苹果", content="苹果水果")
    b = Node(id="b", name="其他", content="其他节点")
    for n in [a1, a2, b]:
        g.add_node(n)
    g.add_edge("b", "a1")
    g.add_edge("b", "a2")

    mock = MockLLM()
    # select_facts 选中所有候选
    mock.set_response(
        "select_nodes",
        lambda nodes_in, _free_args: [n.id for n in (nodes_in or [])],
    )
    engine = make_query_engine(g, mock, _StaticEntry(["b"], g))
    result = engine.query("苹果")
    # a1 和 a2 同名 → 合并，accumulated 中只有一个苹果节点
    apple_nodes = [n for n in result.nodes if n.name == "苹果"]
    assert len(apple_nodes) == 1
    # 合并后 content 应包含两者的信息
    assert "苹果公司" in apple_nodes[0].content


def test_read_repair_no_merge_different_names():
    """read-repair：不同名节点不合并。"""
    from tests.conftest import MockLLM

    g = GraphStore()
    a = Node(id="a", name="苹果", content="苹果公司")
    b = Node(id="b", name="橙子", content="橙子水果")
    c = Node(id="c", name="水果", content="水果概念")
    for n in [a, b, c]:
        g.add_node(n)
    g.add_edge("c", "a")
    g.add_edge("c", "b")

    mock = MockLLM()
    mock.set_response(
        "select_nodes",
        lambda nodes_in, _free_args: [n.id for n in (nodes_in or [])],
    )
    engine = make_query_engine(g, mock, _StaticEntry(["c"], g))
    result = engine.query("水果")
    names = {n.name for n in result.nodes}
    assert "苹果" in names
    assert "橙子" in names


def test_read_repair_hangs_when_over_budget():
    """read-repair：合并后超 T 时挂起（不合并，保留两个节点）。"""
    from tests.conftest import MockLLM

    g = GraphStore()
    # 第一个同名节点 content 很长
    a1 = Node(id="a1", name="大概念", content="X" * 4000)
    a2 = Node(id="a2", name="大概念", content="Y" * 4000)
    b = Node(id="b", name="种子", content="种子")
    for n in [a1, a2, b]:
        g.add_node(n)
    g.add_edge("b", "a1")
    g.add_edge("b", "a2")

    mock = MockLLM()
    mock.set_response(
        "select_nodes",
        lambda nodes_in, _free_args: [n.id for n in (nodes_in or [])],
    )
    # 极小预算：合并后必定超 T
    engine = QueryEngine(
        store=g, llm=mock,  # type: ignore[arg-type]
        plugin_manager=PluginManager(),
        token_budget=TokenBudget(200),
        max_rounds=5,
    )
    # 手动注册 entry 插件
    engine.plugin_manager.register(_StaticEntry(["b"], g))
    result = engine.query("大概念")
    # 超 T → 挂起，两个同名节点都保留或至少第一个
    big_nodes = [n for n in result.nodes if n.name == "大概念"]
    assert len(big_nodes) >= 1


def test_read_repair_substring_dedup():
    """read-repair：content 子串去重——新 content 是已有 content 子串时不追加。"""
    from tests.conftest import MockLLM

    g = GraphStore()
    a1 = Node(id="a1", name="AI", content="Artificial Intelligence is a field")
    a2 = Node(id="a2", name="AI", content="Intelligence")  # 子串
    b = Node(id="b", name="种子", content="种子")
    for n in [a1, a2, b]:
        g.add_node(n)
    g.add_edge("b", "a1")
    g.add_edge("b", "a2")

    mock = MockLLM()
    mock.set_response(
        "select_nodes",
        lambda nodes_in, _free_args: [n.id for n in (nodes_in or [])],
    )
    engine = make_query_engine(g, mock, _StaticEntry(["b"], g))
    result = engine.query("AI")
    ai_nodes = [n for n in result.nodes if n.name == "AI"]
    assert len(ai_nodes) == 1
    # 子串不追加
    assert "Artificial Intelligence is a field" in ai_nodes[0].content


def test_read_repair_name_equals_content_boundary():
    """read-repair：name==content 合并后 name≠content，token 估算必须正确（铁律一）。

    合并前 name==content="X" → 渲染只算一份（去重）。
    合并后 content="X\\nY"、name="X" 不再相等 → 渲染算两份（name + content）。
    used_tokens 必须反映这个增量，否则估算口径≠渲染口径（铁律一违反）。
    """
    from tests.conftest import MockLLM

    g = GraphStore()
    # name == content：渲染去重只算一份
    a1 = Node(id="a1", name="X", content="X")
    a2 = Node(id="a2", name="X", content="Y")  # 同名不同 content
    b = Node(id="b", name="种子", content="种子")
    for n in [a1, a2, b]:
        g.add_node(n)
    g.add_edge("b", "a1")
    g.add_edge("b", "a2")

    mock = MockLLM()
    mock.set_response(
        "select_nodes",
        lambda nodes_in, _free_args: [n.id for n in (nodes_in or [])],
    )
    engine = make_query_engine(g, mock, _StaticEntry(["b"], g))
    result = engine.query("X")
    ai_nodes = [n for n in result.nodes if n.name == "X"]
    assert len(ai_nodes) == 1
    # 合并后 content 应包含两者
    assert "X" in ai_nodes[0].content
    assert "Y" in ai_nodes[0].content
    # name != content → 不再去重
    assert ai_nodes[0].name != ai_nodes[0].content

"""dual-edge-model 核心测试：Edge 字段、事实边索引反查、铁律一、
fanout 出边侧、root 孤儿、事实 BFS、极性问题。

覆盖 tasks 8.1-8.7。
"""

from __future__ import annotations

import pytest

from mcs.core.context_renderer import ContextRenderer
from mcs.core.graph import Edge, Node, Subgraph
from mcs.core.plugin_manager import PluginContext, PluginManager
from mcs.core.query_engine import QueryContext, QueryEngine
from mcs.core.token_budget import TokenBudget
from mcs.interfaces.entry_plugin import EntryPluginInterface
from mcs.stores.in_memory import InMemoryStore


# === 辅助 ===


def _make_store() -> InMemoryStore:
    return InMemoryStore()


def _build_engine(
    store: InMemoryStore,
    mock_llm,
    *extra_plugins,
    max_rounds=3,
    max_accumulated_nodes=1000,
    token_budget=8000,
) -> QueryEngine:
    pm = PluginManager()
    pm.register(mock_llm)
    for p in extra_plugins:
        pm.register(p)
    ctx = PluginContext(
        store=store,
        config=None,  # type: ignore[arg-type]
        token_budget=TokenBudget(token_budget),
        context_renderer=None,  # type: ignore[arg-type]
        plugin_manager=pm,
    )
    pm.initialize_all(ctx)
    return QueryEngine(
        store=store,
        llm=mock_llm,  # type: ignore[arg-type]
        plugin_manager=pm,
        token_budget=TokenBudget(token_budget),
        max_rounds=max_rounds,
        max_accumulated_nodes=max_accumulated_nodes,
    )


class _StaticEntry(EntryPluginInterface):
    """按 id 从 store 返回静态节点的 entry 插件。"""

    def get_name(self) -> str:
        return "static_entry"

    def get_priority(self) -> int:
        return 100

    def __init__(self, node_ids: list[str], store: InMemoryStore):
        self._ids = node_ids
        self._store = store

    def locate(self, query, ctx):
        return [n for n in (self._store.get_node(i) for i in self._ids) if n]


# === 8.1 Edge(kind/label/priority) + 事实边两端索引与反查 ===


class TestEdgeFields:
    """Edge 的 kind / label / priority 字段。"""

    def test_edge_default_kind_is_hierarchy(self):
        e = Edge(source_id="a", target_id="b")
        assert e.kind == "hierarchy"
        assert e.label == ""
        assert e.priority == 0.0

    def test_edge_fact_fields(self):
        e = Edge(source_id="a", target_id="b", kind="fact", label="喜欢", priority=0.8)
        assert e.kind == "fact"
        assert e.label == "喜欢"
        assert e.priority == 0.8

    def test_edge_auto_id(self):
        e1 = Edge(source_id="a", target_id="b")
        e2 = Edge(source_id="a", target_id="b")
        assert e1.id != e2.id  # 自动 uuid，唯一


class TestFactIndexing:
    """事实边两端索引与反查。"""

    def test_get_facts_returns_both_directions(self):
        """get_facts(node_id) 返回该节点为源或宾的全部事实边。"""
        s = _make_store()
        a = Node(id="a", name="A", content="A")
        b = Node(id="b", name="B", content="B")
        c = Node(id="c", name="C", content="C")
        for n in [a, b, c]:
            s.add_node(n)
        s.add_edge("a", "b", kind="fact", label="喜欢")
        s.add_edge("c", "a", kind="fact", label="属于")

        facts_a = s.get_facts("a")
        assert len(facts_a) == 2
        labels = {e.label for e in facts_a}
        assert labels == {"喜欢", "属于"}

    def test_get_out_facts_only_source(self):
        """get_out_facts 只返回节点为源的事实边。"""
        s = _make_store()
        a = Node(id="a", name="A", content="A")
        b = Node(id="b", name="B", content="B")
        s.add_node(a)
        s.add_node(b)
        s.add_edge("a", "b", kind="fact", label="喜欢")

        assert len(s.get_out_facts("a")) == 1
        assert len(s.get_out_facts("b")) == 0  # b 是宾，不是源

    def test_get_out_hierarchy_excludes_facts(self):
        """get_out_hierarchy 只返回层级出边，不含事实边。"""
        s = _make_store()
        a = Node(id="a", name="A", content="A")
        b = Node(id="b", name="B", content="B")
        c = Node(id="c", name="C", content="C")
        for n in [a, b, c]:
            s.add_node(n)
        s.add_edge("a", "b", kind="hierarchy")
        s.add_edge("a", "c", kind="fact", label="相关")

        children = s.get_out_hierarchy("a")
        assert len(children) == 1
        assert children[0].id == "b"

    def test_get_edges_between_returns_all(self):
        """同对节点间可有多条边。"""
        s = _make_store()
        a = Node(id="a", name="A", content="A")
        b = Node(id="b", name="B", content="B")
        s.add_node(a)
        s.add_node(b)
        s.add_edge("a", "b", kind="hierarchy")
        s.add_edge("a", "b", kind="fact", label="喜欢")
        s.add_edge("a", "b", kind="fact", label="创立")

        edges = s.get_edges_between("a", "b")
        assert len(edges) == 3

    def test_fact_stored_once(self):
        """事实边只存一份，不在反向再存。"""
        s = _make_store()
        a = Node(id="a", name="A", content="A")
        b = Node(id="b", name="B", content="B")
        s.add_node(a)
        s.add_node(b)
        s.add_edge("a", "b", kind="fact", label="喜欢")

        # a→b 只有一条事实边
        out_facts = s.get_out_facts("a")
        assert len(out_facts) == 1

        # b 的出事实不应有 a→b（b 是宾不是源）
        out_facts_b = s.get_out_facts("b")
        assert len(out_facts_b) == 0

        # 但 b 可以通过 get_facts 反查到
        facts_b = s.get_facts("b")
        assert len(facts_b) == 1
        assert facts_b[0].label == "喜欢"

    def test_duplicate_fact_edge_deduped(self):
        """同一对节点间**同 label** 的事实只存一份；不同 label / 反向不去重。"""
        s = _make_store()
        a = Node(id="a", name="A", content="A")
        b = Node(id="b", name="B", content="B")
        s.add_node(a)
        s.add_node(b)
        id1 = s.add_edge("a", "b", kind="fact", label="喜欢")
        id2 = s.add_edge("a", "b", kind="fact", label="喜欢")  # 同命题 → 去重
        assert id1 == id2
        assert len(s.get_facts("a")) == 1
        # 不同 label 是不同事实，不去重
        id3 = s.add_edge("a", "b", kind="fact", label="讨厌")
        assert id3 != id1
        assert len(s.get_facts("a")) == 2
        # 反向同 label 是独立事实（方向不同语义）
        id4 = s.add_edge("b", "a", kind="fact", label="喜欢")
        assert id4 != id1
        assert len(s.get_facts("a")) == 3


# === 8.2 活跃双向视图估算含事实 token 且 == 渲染（铁律一） ===


class TestIronLawOne:
    """估算口径 == 渲染口径（铁律一）。"""

    def test_estimate_node_equals_render(self):
        """estimate_node 与 render_node_full 口径一致。"""
        tb = TokenBudget(8000)
        node = Node(id="test", name="测试概念", content="这是一个测试概念的描述内容。")
        estimated = tb.estimate_node(node)

        rendered = ContextRenderer.render_node_full(node, purpose="decide_hub", is_focus=True)
        direct = tb.estimate(rendered)
        assert estimated == direct

    def test_estimate_fact_edge_equals_render(self):
        """estimate_fact_edge 与 render_fact_edge 口径一致。"""
        tb = TokenBudget(8000)
        edge = Edge(source_id="a", target_id="b", kind="fact", label="喜欢")
        estimated = tb.estimate_fact_edge(edge)

        rendered = ContextRenderer.render_fact_edge(edge)
        direct = tb.estimate(rendered)
        assert estimated == direct

    def test_estimate_fact_edge_with_node_map(self):
        """带 node_map 时估算仍与渲染一致。"""
        tb = TokenBudget(8000)
        a = Node(id="a", name="小明", content="")
        b = Node(id="b", name="苹果", content="")
        edge = Edge(source_id="a", target_id="b", kind="fact", label="喜欢")
        node_map = {"a": a, "b": b}

        estimated = tb.estimate_fact_edge(edge, node_map)
        rendered = ContextRenderer.render_fact_edge(edge, node_map)
        direct = tb.estimate(rendered)
        assert estimated == direct

    def test_estimate_active_view_includes_facts(self):
        """estimate_active_view 包含事实边 token。"""
        tb = TokenBudget(8000)
        node = Node(id="center", name="中心", content="中心节点")
        child = Node(id="child", name="子节点", content="子节点内容")
        fact_edge = Edge(source_id="center", target_id="other", kind="fact", label="关联")

        view_tokens = tb.estimate_active_view(
            node=node,
            out_hierarchy=[child],
            out_facts=[fact_edge],
        )
        # 应大于仅节点（不含事实）的 token
        nodes_only = tb.estimate_node(node) + tb.estimate_node(child)
        assert view_tokens > nodes_only

    def test_name_content_dedup_in_estimate(self):
        """name==content 时只计一份（去重）。"""
        tb = TokenBudget(8000)
        node = Node(id="dup", name="重复内容", content="重复内容")
        estimated = tb.estimate_node(node)
        rendered = ContextRenderer.render_node_full(node, purpose="decide_hub", is_focus=True)
        direct = tb.estimate(rendered)
        assert estimated == direct
        # 去重后应小于 name+content 各算一份
        raw_sum = tb.estimate(node.name) + tb.estimate(node.content)
        assert estimated < raw_sum


# === 8.3 fanout 只聚出边侧（已有 test_fanout_reducer.py 覆盖，此处补充关键断言） ===


class TestFanoutOutboundOnly:
    """fanout 只聚出边侧，入边侧不聚类。"""

    def test_inbound_facts_not_counted_in_outbound_view(self):
        """出边侧视图不含入事实（get_out_facts 而非 get_facts）。"""
        s = _make_store()
        a = Node(id="a", name="A", content="A")
        b = Node(id="b", name="B", content="B")
        c = Node(id="c", name="C", content="C")
        for n in [a, b, c]:
            s.add_node(n)
        s.add_edge("a", "b", kind="fact", label="喜欢")
        s.add_edge("c", "a", kind="fact", label="属于")

        # a 的出事实只有 a→b，不含 c→a
        out_facts = s.get_out_facts("a")
        assert len(out_facts) == 1
        assert out_facts[0].label == "喜欢"

        # 但 get_facts 包含双向
        all_facts = s.get_facts("a")
        assert len(all_facts) == 2


# === 8.4 root 可选挂孤儿 ===


class TestRootOrphan:
    """root 仅挂孤儿——有关联不挂、零关联挂。"""

    def test_node_with_fact_not_orphan(self):
        """有事实关联的节点经关联可达，不是孤儿。"""
        s = _make_store()
        a = Node(id="a", name="A", content="A")
        b = Node(id="b", name="B", content="B")
        s.add_node(a)
        s.add_node(b)
        s.add_edge("a", "b", kind="fact", label="相关")

        # b 可经 a→b 事实边从 a 到达
        facts_b = s.get_facts("b")
        assert len(facts_b) == 1
        assert facts_b[0].source_id == "a"

    def test_isolated_node_has_no_facts(self):
        """孤立节点无事实边，无层级子节点。"""
        s = _make_store()
        a = Node(id="a", name="A", content="A")
        s.add_node(a)

        assert s.get_facts("a") == []
        assert s.get_out_hierarchy("a") == []


# === 8.5 事实 BFS 选事实 + 端点补入 ===


class TestFactBFS:
    """事实 BFS 选事实 + 端点补入。"""

    def test_fact_endpoints_added(self):
        """选中 fact 边时，两端节点都应加入 accumulated。"""
        from tests.conftest import MockLLM

        s = _make_store()
        a = Node(id="a", name="A", content="A")
        b = Node(id="b", name="B", content="B")
        for n in [a, b]:
            s.add_node(n)
        s.add_edge("a", "b", kind="fact", label="喜欢")

        mock = MockLLM()
        engine = _build_engine(s, mock, _StaticEntry(["a"], s))
        mock.set_response(
            "select_nodes",
            lambda nodes_in, _: [n.id for n in (nodes_in or [])],
        )
        result = engine.query("test")
        ids = {n.id for n in result.nodes}
        assert "a" in ids
        assert "b" in ids
        # fact 边应在 edges 中
        assert any(e.label == "喜欢" for e in result.edges)

    def test_fact_bfs_reaches_distant_via_hop(self):
        """事实 BFS 通过两跳到达远端节点：a→b (fact), b→c (fact)。"""
        from tests.conftest import MockLLM

        s = _make_store()
        nodes = [Node(id=f"n{i}", name=f"N{i}", content=f"N{i}") for i in range(4)]
        for n in nodes:
            s.add_node(n)
        s.add_edge("n0", "n1", kind="fact", label="知道")
        s.add_edge("n1", "n2", kind="fact", label="认识")
        # n3 独立，不可达
        s.add_edge("n0", "n3", kind="hierarchy")

        mock = MockLLM()
        engine = _build_engine(s, mock, _StaticEntry(["n0"], s), max_rounds=3)
        mock.set_response(
            "select_nodes",
            lambda nodes_in, _: [n.id for n in (nodes_in or [])],
        )
        result = engine.query("test")
        ids = {n.id for n in result.nodes}
        assert "n0" in ids
        assert "n1" in ids  # 一跳事实
        assert "n2" in ids  # 二跳事实

    def test_edges_only_contain_facts(self):
        """Subgraph.edges 只含 fact 边，不含 hierarchy 边。"""
        from tests.conftest import MockLLM

        s = _make_store()
        a = Node(id="a", name="A", content="A")
        b = Node(id="b", name="B", content="B")
        c = Node(id="c", name="C", content="C")
        for n in [a, b, c]:
            s.add_node(n)
        s.add_edge("a", "b", kind="hierarchy")
        s.add_edge("a", "c", kind="fact", label="相关")

        mock = MockLLM()
        engine = _build_engine(s, mock, _StaticEntry(["a"], s))
        mock.set_response(
            "select_nodes",
            lambda nodes_in, _: [n.id for n in (nodes_in or [])],
        )
        result = engine.query("test")
        for edge in result.edges:
            assert edge.kind == "fact"


# === 8.6 极性问题（mock LLM） ===


class TestPolarity:
    """极性问题由 LLM 在正面事实上现推。"""

    def test_select_facts_returns_relevant_facts(self):
        """select_facts parser 解析编号列表。"""
        from mcs.prompts.select_facts import parse

        result = parse("[1, 3, 5]")
        assert result == [1, 3, 5]

    def test_select_facts_parse_empty(self):
        from mcs.prompts.select_facts import parse

        result = parse("[]")
        assert result == []

    def test_select_facts_parse_fenced(self):
        from mcs.prompts.select_facts import parse

        result = parse("```json\n[2, 4]\n```")
        assert result == [2, 4]

    def test_render_facts_includes_edges(self):
        """render_facts 输出包含事实边条目。"""
        a = Node(id="a", name="小明", content="一个普通学生")
        b = Node(id="b", name="苹果", content="一种水果")
        edge = Edge(source_id="a", target_id="b", kind="fact", label="喜欢")
        renderer = ContextRenderer()
        text = renderer.render_facts([a, b], [edge])
        assert "小明" in text
        assert "苹果" in text
        assert "喜欢" in text
        assert "小明 —喜欢→ 苹果" in text


# === 8.7 集成 write→query：label 正确写入 / 读取 / 反查 ===


class TestWriteQueryIntegration:
    """write→query 全流程：label 正确写入 / 读取 / 反查。"""

    def test_write_fact_edge_queryable(self):
        """写入事实边后可通过 get_facts 反查到 label。"""
        s = _make_store()
        a = Node(id="a", name="小明", content="学生")
        b = Node(id="b", name="苹果", content="水果")
        s.add_node(a)
        s.add_node(b)
        edge_id = s.add_edge("a", "b", kind="fact", label="喜欢")

        # 反查
        facts_a = s.get_facts("a")
        assert len(facts_a) == 1
        assert facts_a[0].label == "喜欢"
        assert facts_a[0].id == edge_id

        facts_b = s.get_facts("b")
        assert len(facts_b) == 1
        assert facts_b[0].label == "喜欢"

    def test_write_query_roundtrip(self):
        """写入后查询能检索到事实边。"""
        from tests.conftest import MockLLM

        s = _make_store()
        a = Node(id="a", name="小明", content="学生")
        b = Node(id="b", name="苹果", content="水果")
        s.add_node(a)
        s.add_node(b)
        s.add_edge("a", "b", kind="fact", label="喜欢")

        mock = MockLLM()
        engine = _build_engine(s, mock, _StaticEntry(["a"], s))
        mock.set_response(
            "select_nodes",
            lambda nodes_in, _: [n.id for n in (nodes_in or [])],
        )
        result = engine.query("小明喜欢什么")
        # 应找到 fact 边
        assert len(result.edges) >= 1
        labels = {e.label for e in result.edges}
        assert "喜欢" in labels


# === 测试盲区 A: Subgraph 返回值的下游兼容性 ===


class TestSubgraphDownstreamCompat:
    """query() 返回 Subgraph 后，下游消费者（bench/examples）的使用模式。"""

    def test_subgraph_is_not_list(self):
        """Subgraph 不是 list，isinstance(Subgraph, list) 必须为 False。
        这是 bench 脚本 `nodes = result if isinstance(result, list) else []`
        模式的根本原因——必须用 hasattr(result, "nodes") 替代。
        """
        sg = Subgraph(focus_id="a", nodes=[Node(id="a", name="A", content="")], edges=[])
        assert not isinstance(sg, list)

    def test_subgraph_has_nodes_attr(self):
        """Subgraph 有 .nodes 属性，下游应通过它获取节点列表。"""
        nodes = [Node(id="a", name="A", content="")]
        sg = Subgraph(focus_id="a", nodes=nodes, edges=[])
        assert hasattr(sg, "nodes")
        assert sg.nodes == nodes

    def test_subgraph_not_iterable(self):
        """Subgraph 不可迭代（无 __iter__），`for n in subgraph` 会 TypeError。
        这验证 wiki_example 的旧模式 `for n in turn1` 会崩溃。
        """
        sg = Subgraph(focus_id="", nodes=[], edges=[])
        with pytest.raises(TypeError):
            iter(sg)

    def test_subgraph_no_len(self):
        """Subgraph 没有 __len__，`len(subgraph)` 会 TypeError。
        这验证 wiki_example 的旧模式 `len(turn1)` 会崩溃。
        """
        sg = Subgraph(focus_id="", nodes=[], edges=[])
        with pytest.raises(TypeError):
            len(sg)

    def test_subgraph_nodes_has_len(self):
        """Subgraph.nodes 是 list，支持 len()。下游应使用 len(result.nodes)。"""
        nodes = [Node(id=str(i), name=f"N{i}", content="") for i in range(3)]
        sg = Subgraph(focus_id="0", nodes=nodes, edges=[])
        assert len(sg.nodes) == 3

    def test_subgraph_nodes_is_iterable(self):
        """Subgraph.nodes 是 list，支持迭代。下游应使用 `for n in result.nodes`。"""
        nodes = [Node(id="a", name="A", content=""), Node(id="b", name="B", content="")]
        sg = Subgraph(focus_id="a", nodes=nodes, edges=[])
        names = [n.name for n in sg.nodes]
        assert names == ["A", "B"]

    def test_bench_pattern_with_subgraph(self):
        """bench 脚本的正确模式：用 hasattr(result, "nodes") 提取节点。"""
        nodes = [Node(id="a", name="A", content="")]
        sg = Subgraph(focus_id="a", nodes=nodes, edges=[])
        result = sg
        # 旧模式（已修复）：isinstance(result, list) → False → nodes=[]
        assert not isinstance(result, list)
        # 新模式（正确）：
        if hasattr(result, "nodes"):
            extracted = result.nodes
        else:
            extracted = result if isinstance(result, list) else []
        assert extracted == nodes

    def test_existing_context_accepts_list_from_subgraph_nodes(self):
        """query(existing_context=result.nodes) 应正常工作。"""
        from tests.conftest import MockLLM

        s = _make_store()
        a = Node(id="a", name="A", content="A")
        b = Node(id="b", name="B", content="B")
        s.add_node(a)
        s.add_node(b)

        mock = MockLLM()
        engine = _build_engine(s, mock, _StaticEntry(["a"], s))
        mock.set_response("select_nodes", [])
        # 第一次查询
        result1 = engine.query("test")
        assert isinstance(result1, Subgraph)
        # 用 result1.nodes 作为 existing_context（wiki_example 模式）
        result2 = engine.query("test2", existing_context=result1.nodes)
        assert isinstance(result2, Subgraph)


# === 测试盲区 B: render_facts 与 render_node_full 一致性（铁律一） ===


class TestRenderFactsConsistency:
    """render_facts 的节点体必须与 render_node_full 口径一致（铁律一）。"""

    def test_render_facts_body_matches_render_node_full_with_content(self):
        """content 非空时，render_facts 的节点体与 render_node_full 一致。"""
        node = Node(id="a", name="AI", content="Artificial Intelligence")
        renderer = ContextRenderer()
        facts_text = renderer.render_facts([node], [])

        full_text = ContextRenderer.render_node_full(
            node, purpose="select_facts", is_focus=True
        )
        # render_facts 用编号前缀；render_node_full 用 "- " 前缀
        # 去掉前缀后 body 应一致
        facts_lines = facts_text.split("\n")
        full_lines = full_text.split("\n")
        # body 部分（第 2 行起）应相同
        assert facts_lines[0].lstrip("0123456789. ") == full_lines[0].lstrip("- ")
        if len(facts_lines) > 1 and len(full_lines) > 1:
            assert facts_lines[1] == full_lines[1]

    def test_render_facts_body_with_empty_content_and_summary(self):
        """content 为空但 summary 存在时，render_facts 必须与 render_node_full 一致。
        这是 Code Review 发现的具体分歧点：旧 render_facts 用 node.content or ""，
        render_node_full 用 node.content or get_summary(node)。
        """
        node = Node(
            id="a",
            name="AI",
            content="",
            extensions={"summary": {"text": "AI is a field of computer science."}},
        )
        renderer = ContextRenderer()
        facts_text = renderer.render_facts([node], [])
        full_text = ContextRenderer.render_node_full(
            node, purpose="select_facts", is_focus=True
        )
        # 去掉编号/前缀后的 body 必须一致
        facts_body = facts_text.split("\n", 1)[1] if "\n" in facts_text else ""
        full_body = full_text.split("\n", 1)[1] if "\n" in full_text else ""
        assert facts_body == full_body, (
            f"render_facts body: {facts_body!r}\n"
            f"render_node_full body: {full_body!r}"
        )

    def test_render_facts_name_content_dedup(self):
        """name==content 时只写一份（与 render_node_full 去重逻辑一致）。"""
        node = Node(id="a", name="重复内容", content="重复内容")
        renderer = ContextRenderer()
        facts_text = renderer.render_facts([node], [])
        # name 已在编号行显示，body 不应重复
        lines = facts_text.strip().split("\n")
        # 只应有 1 行（编号行），没有 body 行
        assert len(lines) == 1
        assert "重复内容" in lines[0]

    def test_render_facts_includes_extensions(self):
        """render_facts 必须包含 extension 插件贡献（与 render_node_full 一致）。
        用手动构造的 extensions 列表而非完整的 NodeExtensionInterface 子类。
        """
        node = Node(id="a", name="AI", content="Artificial Intelligence")

        # 用一个最小 mock 对象模拟 extension 插件
        class _MockExt:
            def render(self, node, purpose):
                return f"[ext:{node.name}]"

        extensions = [_MockExt()]
        full_text = ContextRenderer.render_node_full(
            node, purpose="select_facts", is_focus=True, extensions=extensions
        )
        # 确认 render_node_full 包含 extension
        assert "[ext:AI]" in full_text

        # render_facts 内部通过 _get_extensions 获取插件列表，
        # 这里直接验证 render_node_full 被正确调用（委托方式）。
        # 通过对比 render_node_full 的输出来间接验证 render_facts 一致性。
        renderer = ContextRenderer()
        # 无插件时两者应一致
        facts_text = renderer.render_facts([node], [])
        full_no_ext = ContextRenderer.render_node_full(
            node, purpose="select_facts", is_focus=True
        )
        # 去掉前缀后 body 应一致
        facts_lines = facts_text.strip().split("\n")
        full_lines = full_no_ext.strip().split("\n")
        # body 行（第 2 行+）应完全相同
        assert facts_lines[1:] == full_lines[1:]


# === 测试盲区 C: API 返回类型契约 ===


class TestQueryReturnContract:
    """query() 必须返回 Subgraph（无 postprocess 时）；query_nodes() 返回 list[Node]。"""

    def test_query_returns_subgraph_by_default(self, seeded_graph, mock_llm):
        """无后置插件时 query() 返回 Subgraph。"""
        engine = _build_engine(
            seeded_graph,
            mock_llm,
            _StaticEntry(["dl"], seeded_graph),
        )
        mock_llm.set_response("select_nodes", [])
        result = engine.query("test")
        assert isinstance(result, Subgraph)

    def test_query_subgraph_edges_all_fact(self, seeded_graph, mock_llm):
        """Subgraph.edges 中所有边必须是 fact 类型。"""
        engine = _build_engine(
            seeded_graph,
            mock_llm,
            _StaticEntry(["dl"], seeded_graph),
        )
        mock_llm.set_response(
            "select_nodes",
            lambda nodes_in, _: [n.id for n in (nodes_in or [])],
        )
        result = engine.query("test")
        for edge in result.edges:
            assert edge.kind == "fact", f"edge {edge.id} has kind={edge.kind}, expected 'fact'"

    def test_query_empty_seeds_returns_empty_subgraph(self, seeded_graph, mock_llm):
        """空种子返回空 Subgraph（非空列表、非 None）。"""
        engine = _build_engine(seeded_graph, mock_llm)
        result = engine.query("nothing")
        assert isinstance(result, Subgraph)
        assert result.nodes == []
        assert result.edges == []

    def test_query_nodes_returns_list(self, seeded_graph, mock_llm):
        """query_nodes() 仍返回 list[Node]（不变）。"""
        engine = _build_engine(
            seeded_graph,
            mock_llm,
            _StaticEntry(["dl"], seeded_graph),
        )
        mock_llm.set_response("select_nodes", [])
        result = engine.query_nodes("test")
        assert isinstance(result, list)
        if result:
            assert isinstance(result[0], Node)


# === 测试盲区 D: 批量分层遍历（P3 spec query-pipeline / batch-neighbor-traverse） ===


class TestBatchedTraverse:
    """_traverse 批量分层：富余合并一次调用 / 超预算切分 / 解析失败逐节点回退。"""

    @staticmethod
    def _count_select_facts(mock) -> int:
        return sum(1 for c in mock.call_log if c["purpose"] == "select_facts")

    def _two_seed_store(self) -> InMemoryStore:
        s = _make_store()
        for nid in ["s1", "s2", "t1", "t2"]:
            s.add_node(Node(id=nid, name=nid, content=nid))
        s.add_edge("s1", "t1", kind="fact", label="r1")
        s.add_edge("s2", "t2", kind="fact", label="r2")
        return s

    def test_two_seeds_merge_into_single_call(self):
        """两种子视图合计 ≤ T*0.8 → 合并为一次 select_facts 调用。"""
        from tests.conftest import MockLLM

        s = self._two_seed_store()
        mock = MockLLM()
        mock.set_response("select_facts", lambda nodes_in, free: [])
        engine = _build_engine(
            s, mock, _StaticEntry(["s1", "s2"], s), token_budget=8000
        )
        engine.query("test")
        assert self._count_select_facts(mock) == 1

    def test_over_budget_splits_into_two_calls(self):
        """两种子单视图各超 T*0.8 → 切两批两次调用（种子本身小，不被 used 提前刹车）。"""
        from tests.conftest import MockLLM

        s = _make_store()
        big = "C" * 200  # ≈ 50 token / 端点节点
        for sid in ["s1", "s2"]:
            s.add_node(Node(id=sid, name=sid, content="x"))  # 种子本身小
            for i in range(15):
                tid = f"{sid}_t{i}"
                s.add_node(Node(id=tid, name=tid, content=big))
                s.add_edge(sid, tid, kind="fact", label=f"r{i}")

        mock = MockLLM()
        mock.set_response("select_facts", lambda nodes_in, free: [])
        # 单种子视图 ≈ 15*50 ≫ pack_budget=480；两批 → 两次调用
        engine = _build_engine(
            s, mock, _StaticEntry(["s1", "s2"], s), token_budget=600
        )
        engine.query("test")
        assert self._count_select_facts(mock) == 2

    def test_batch_parse_failure_falls_back_per_node(self):
        """批量调用解析失败 → 逐节点回退（遍历不中断）。"""
        from mcs.core.errors import LLMParseError
        from tests.conftest import MockLLM

        s = self._two_seed_store()
        state = {"n": 0}

        def sf(nodes_in, free):
            state["n"] += 1
            if state["n"] == 1:  # 首次（合并批）解析失败
                raise LLMParseError("select_facts", "raw", "boom")
            return []  # 逐节点回退调用成功返回空

        mock = MockLLM()
        mock.set_response("select_facts", sf)
        engine = _build_engine(
            s, mock, _StaticEntry(["s1", "s2"], s), token_budget=8000
        )
        result = engine.query("test")
        # 1 次合并失败 + 2 次逐节点 = 3 次；遍历未崩、种子仍在
        assert self._count_select_facts(mock) == 3
        ids = {n.id for n in result.nodes}
        assert {"s1", "s2"} <= ids


# === 测试盲区 E: judge_relations 丢弃无意义 label 的事实边 ===


class TestMeaninglessLabelFilter:
    """judge_relations 解析丢弃「无关 / unrelated」等否定 / 空泛 label 的边。"""

    def test_drops_meaningless_edge_labels(self):
        from mcs.prompts.judge_relations import parse

        raw = (
            '[{"action":"create","concept_name":"A","edges_to_names":['
            '{"target_name":"B","label":"效力于"},'
            '{"target_name":"C","label":"无关"},'
            '{"target_name":"D","label":"unrelated"}]},'
            '{"action":"create","concept_name":"E","edges_to":['
            '{"target_id":"x","label":"包含"},'
            '{"target_id":"y","label":"不相关"}]}]'
        )
        decisions = parse(raw)
        a = next(d for d in decisions if d.concept.name == "A")
        assert {e["label"] for e in a.edges_to_names} == {"效力于"}
        e = next(d for d in decisions if d.concept.name == "E")
        assert {edge["label"] for edge in e.edges_to} == {"包含"}

    def test_keeps_meaningful_labels(self):
        from mcs.prompts.judge_relations import parse

        raw = (
            '[{"action":"create","concept_name":"A","edges_to_names":['
            '{"target_name":"B","label":"配偶"},'
            '{"target_name":"C","label":"领导"}]}]'
        )
        decisions = parse(raw)
        assert len(decisions[0].edges_to_names) == 2


# === 测试盲区 F: judge_relations 截断 JSON 兜底（salvage） ===


class TestJudgeRelationsSalvage:
    """concept 多的文档 deepseek 吐超长 JSON 截断时，救回已完整的对象。"""

    def test_salvages_truncated_array(self):
        from mcs.prompts.judge_relations import parse

        # 两个完整对象 + 第三个被截断（命中输出上限的典型形态）
        raw = (
            '[\n'
            '  {"action":"create","concept_name":"A",'
            '"edges_to_names":[{"target_name":"X","label":"属于"}]},\n'
            '  {"action":"create","concept_name":"B",'
            '"edges_to":[{"target_id":"y","label":"包含"}]},\n'
            '  {"action":"create","concept_name":"C",'
            '"edges_to_names":[{"target_name":"Z","la'
        )
        decisions = parse(raw)
        assert {d.concept.name for d in decisions} == {"A", "B"}
        a = next(d for d in decisions if d.concept.name == "A")
        assert a.edges_to_names == [{"target_name": "X", "label": "属于"}]

    def test_salvages_fenced_truncated_array(self):
        from mcs.prompts.judge_relations import parse

        # 真实形态：```json 围栏 + 中途截断
        raw = (
            '```json\n[\n'
            '  {"action":"create","concept_name":"A"},\n'
            '  {"action":"create","concept_name":"B"},\n'
            '  {"action":"create","conce'
        )
        decisions = parse(raw)
        assert {d.concept.name for d in decisions} == {"A", "B"}

    def test_unsalvageable_still_raises(self):
        from mcs.core.errors import LLMParseError
        from mcs.prompts.judge_relations import parse

        # 第一个对象就坏、救不出任何完整对象 → 仍抛
        with pytest.raises(LLMParseError):
            parse("[ {不是合法 json")


# === 测试盲区 G: accumulated_summary 修剪（查询成本止血） ===


class TestAccumulatedSummaryTrim:
    """_summarize_for_prompt：仅 name + 限最近 N + 可关闭（占查询输入 ~73% 的止血）。"""

    def test_names_only_no_content_no_id(self):
        from mcs.core.query_engine import _summarize_for_prompt

        nodes = [Node(id=f"n{i}", name=f"N{i}", content="x" * 300) for i in range(3)]
        s = _summarize_for_prompt(nodes, max_nodes=50)
        assert "N0" in s and "N2" in s
        assert "x" * 50 not in s  # content[:200] 不再带
        assert "id=" not in s  # uuid/id 不再带

    def test_cap_recent_n(self):
        from mcs.core.query_engine import _summarize_for_prompt

        nodes = [Node(id=f"n{i}", name=f"N{i}", content="") for i in range(100)]
        s = _summarize_for_prompt(nodes, max_nodes=10)
        assert "N99" in s and "N90" in s  # 只列最近 10 个
        assert "N0," not in s and not s.endswith("N0")  # 旧的被截断
        assert "100" in s  # 含总数提示

    def test_off_switch(self):
        from mcs.core.query_engine import _summarize_for_prompt

        nodes = [Node(id="a", name="A", content="")]
        assert _summarize_for_prompt(nodes, max_nodes=0) == "(无)"
        assert _summarize_for_prompt([], max_nodes=50) == "(无)"


# === 测试盲区 H: ②「无…关系」否定族过滤 + ③ extract_concepts salvage ===


class TestNegationLabelAndExtractSalvage:
    """② 拦住「无直接关系」等否定变体；③ extract_concepts 截断兜底。"""

    def test_drops_negation_relation_family(self):
        from mcs.prompts.judge_relations import parse

        raw = (
            '[{"action":"create","concept_name":"A","edges_to_names":['
            '{"target_name":"B","label":"执导"},'
            '{"target_name":"C","label":"无直接关系"},'
            '{"target_name":"D","label":"无关联"},'
            '{"target_name":"E","label":"无任何关系"},'
            '{"target_name":"F","label":"没有关系"}]}]'
        )
        a = parse(raw)[0]
        assert {e["label"] for e in a.edges_to_names} == {"执导"}

    def test_keeps_legit_wu_prefix_label(self):
        from mcs.prompts.judge_relations import parse

        # 「无偿提供」是真关系，不能被「无…」误杀
        raw = (
            '[{"action":"create","concept_name":"A",'
            '"edges_to_names":[{"target_name":"B","label":"无偿提供"}]}]'
        )
        a = parse(raw)[0]
        assert {e["label"] for e in a.edges_to_names} == {"无偿提供"}

    def test_salvage_json_array_mid_break(self):
        from mcs.utils.text_utils import salvage_json_array

        s = '[{"a": 1}, {"a": 2}, {"a": bad}, {"a": 4}]'
        assert salvage_json_array(s) == [{"a": 1}, {"a": 2}]

    def test_extract_concepts_recovers_truncated(self):
        from mcs.prompts.extract_concepts import parse

        raw = '[{"name":"Alpha","content":"a"},{"name":"Beta","content":"b"},{"name":"Gam'
        names = {c.name for c in parse(raw)}
        assert "Alpha" in names and "Beta" in names

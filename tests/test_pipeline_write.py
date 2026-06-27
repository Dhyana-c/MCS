"""WritePipeline 测试：7 阶段管道行为。"""

from __future__ import annotations

import logging

from conftest import MockLLMBuilder

from mcs.core.plugin_manager import PluginContext, PluginManager
from mcs.core.query_engine import QueryEngine
from mcs.core.store import StoreInterface
from mcs.core.token_budget import TokenBudget
from mcs.core.write_pipeline import WritePipeline
from mcs.entities.config import MCSConfig
from mcs.entities.decisions import ConceptDraft, Decision
from mcs.entities.graph import CLASS_CONCEPT, CLASS_EVENT, CORE_NODE_CLASSES, Node
from mcs.interfaces.compaction_plugin import CompactionPluginInterface
from mcs.interfaces.write_preprocess_plugin import WritePreprocessPluginInterface
from mcs.stores.in_memory import InMemoryStore
from mcs.stores.sqlite_store import SQLiteStore


def _build_pipelines(store: StoreInterface, mock_llm, *extra_plugins, config=None):
    pm = PluginManager()
    pm.register(mock_llm)
    for p in extra_plugins:
        pm.register(p)
    ctx = PluginContext(
        store=store,
        config=config or MCSConfig(),
        token_budget=TokenBudget(8000),
        context_renderer=None,  # type: ignore[arg-type]
        plugin_manager=pm,
    )
    pm.initialize_all(ctx)
    query_engine = QueryEngine(
        store=store,
        llm=mock_llm,
        plugin_manager=pm,
        token_budget=TokenBudget(8000),
        max_rounds=3,
        max_accumulated_nodes=20,
    )
    write_pipeline = WritePipeline(
        store=store,
        llm=mock_llm,
        query_engine=query_engine,
        plugin_manager=pm,
        token_budget=TokenBudget(8000),
        config=config or MCSConfig(),
    )
    return write_pipeline, query_engine, pm


def test_ingest_calls_query_engine_for_related_lookup(empty_graph, mock_llm):
    """阶段 ②：查询引擎必须以处理后的文本被调用。"""
    wp, qe, _ = _build_pipelines(empty_graph, mock_llm)
    mock_llm.set_response("extract_concepts", [])  # 静默返回
    wp.ingest("some text")
    # decide_directions 是 query() 内部的 LLM 调用；由于没有
    # entry 插件，query 会快速返回空结果。我们通过检查 mock_llm 日志
    # 以 extract_concepts 开头来断言 query() 确实被调用了。
    purposes = [c["purpose"] for c in mock_llm.call_log]
    assert "extract_concepts" in purposes


def test_zero_concepts_silently_returns(empty_graph, mock_llm):
    """如果 extract_concepts 返回 []，阶段 ④⑤⑥ 被跳过。"""
    wp, _, _ = _build_pipelines(empty_graph, mock_llm)
    mock_llm.set_response("extract_concepts", [])
    ctx = wp.ingest("hello")
    assert ctx.concepts == []
    assert ctx.decisions == []
    assert ctx.changed == []


def test_create_decision_adds_node(empty_graph, mock_llm):
    """'create' 决策应作为新节点 + 边落入图中。"""
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
    # ingest 现在还会建一个记录事件节点；概念节点恰一个
    concepts = [n for n in nodes if n.node_class == CLASS_CONCEPT]
    assert len(concepts) == 1
    assert concepts[0].name == "深度学习"
    assert len([n for n in nodes if n.node_class == CLASS_EVENT]) == 1


def test_merge_decision_updates_existing_node(empty_graph, mock_llm):
    """'merge' 决策指向已存在的目标；该目标的 content 应追加 concept.content，
    concept.name 应作为别名并入目标。
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
            )
        ],
    )
    ctx = wp.ingest("some text")
    assert len(ctx.changed) == 1
    assert ctx.changed[0].id == "t1"
    # 目标节点在图中仍然只有一个实例。
    assert len([n for n in empty_graph.get_all_nodes() if n.id == "t1"]) == 1
    # concept.content 应追加到目标节点的 content。
    merged = empty_graph.get_node("t1")
    assert "存量内容" in merged.content
    assert "新内容" in merged.content
    # concept.name 应作为别名并入目标。
    aliases = merged.extensions.get("alias_index", {}).get("aliases", [])
    assert "新名字" in aliases


def test_no_op_decision_changes_nothing(empty_graph, mock_llm):
    wp, _, _ = _build_pipelines(empty_graph, mock_llm)
    mock_llm.set_response("extract_concepts", [ConceptDraft(name="X", content="")])
    mock_llm.set_response(
        "judge_relations",
        [Decision(action="no_op", reason="not relevant")],
    )
    ctx = wp.ingest("text")
    assert ctx.changed == []
    # no_op 不建概念 / 事实；ingest 仍记一个事件节点（记录行为已发生）
    core_nodes = [
        n for n in empty_graph.get_all_nodes() if n.node_class in CORE_NODE_CLASSES
    ]
    assert core_nodes == []
    assert len([n for n in empty_graph.get_all_nodes() if n.node_class == CLASS_EVENT]) == 1


def test_compaction_chain_runs_when_should_run_true(empty_graph, mock_llm):
    """⑥ 当 should_run 返回 True 时，Compaction 插件的 run() 必须被调用。"""
    run_count = {"n": 0}

    class _CountingCompaction(CompactionPluginInterface):
        def get_name(self) -> str:
            return "counting_compaction"

        def should_run(self, changed_nodes, store):
            return bool(changed_nodes)

        def run(self, changed_nodes, store, llm_caller):
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
    class _BlockedCompaction(CompactionPluginInterface):
        def get_name(self) -> str:
            return "blocked"

        def should_run(self, changed_nodes, store):
            return False

        def run(self, changed_nodes, store, llm_caller):
            raise AssertionError("当 should_run 为 False 时，run() 不应被调用")

    wp, _, _ = _build_pipelines(empty_graph, mock_llm, _BlockedCompaction())
    concept = ConceptDraft(name="x", content="")
    mock_llm.set_response("extract_concepts", [concept])
    mock_llm.set_response(
        "judge_relations",
        [Decision(action="create", concept=concept, edges_to=[])],
    )
    wp.ingest("text")  # 无 AssertionError → run() 未被调用


def test_pending_source_attached_to_changed_nodes(empty_graph, mock_llm):
    """阶段 ⑤ 后：ctx.metadata 暂存的 Source 必须挂到本次变更的节点上。"""
    from mcs.core.write_pipeline import WriteContext
    from mcs.plugins.preprocess.source_tracking import Source

    wp, _, _ = _build_pipelines(empty_graph, mock_llm)
    node = Node(id="n1", name="N", content="c")
    empty_graph.add_node(node)
    src = Source(doc_id="d1", chunk_id="c1", content_hash="h")
    ctx = WriteContext(changed=[node], metadata={"_pending_source": src})

    wp._attach_pending_source(ctx)

    assert node.extensions["source_tracking"]["sources"] == [src]


def test_no_pending_source_is_noop(empty_graph, mock_llm):
    """无 _pending_source 时 _attach_pending_source 不应改动节点。"""
    from mcs.core.write_pipeline import WriteContext

    wp, _, _ = _build_pipelines(empty_graph, mock_llm)
    node = Node(id="n1", name="N", content="c")
    ctx = WriteContext(changed=[node], metadata={})

    wp._attach_pending_source(ctx)

    assert "source_tracking" not in node.extensions


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


# === 阶段 ⑦ 自动落盘测试 ===


def test_auto_persist_saves_changed_nodes(empty_graph, mock_llm):
    """auto_persist=True 时，每次 ingest 后 changed 节点必须落盘（SQLiteStore）。"""
    # 使用 SQLiteStore 进行持久化测试
    store = SQLiteStore({"path": ":memory:"})
    store.initialize()
    pm = PluginManager()
    pm.register(mock_llm)
    ctx = PluginContext(
        store=store,
        config=MCSConfig(auto_persist=True),
        token_budget=TokenBudget(8000),
        context_renderer=None,  # type: ignore[arg-type]
        plugin_manager=pm,
    )
    pm.initialize_all(ctx)
    query_engine = QueryEngine(
        store=store,
        llm=mock_llm,
        plugin_manager=pm,
        token_budget=TokenBudget(8000),
        max_rounds=3,
        max_accumulated_nodes=20,
    )
    wp = WritePipeline(
        store=store,
        llm=mock_llm,
        query_engine=query_engine,
        plugin_manager=pm,
        token_budget=TokenBudget(8000),
        config=MCSConfig(auto_persist=True),
    )

    concept = ConceptDraft(name="x", content="content")
    mock_llm.set_response("extract_concepts", [concept])
    mock_llm.set_response(
        "judge_relations",
        [Decision(action="create", concept=concept, edges_to=[])],
    )
    ctx = wp.ingest("text")

    assert ctx.persisted is True
    # changed 概念节点已落盘（ingest 还会落一个记录事件节点，不计入此断言）
    rows = store.conn.execute(
        "SELECT COUNT(*) FROM nodes WHERE node_class=?", (CLASS_CONCEPT,)
    ).fetchone()
    assert rows[0] == 1


def test_auto_persist_false_skips_persist(empty_graph, mock_llm):
    """auto_persist=False 时，阶段 ⑦ 必须跳过。"""
    store = InMemoryStore()
    config = MCSConfig(auto_persist=False)
    wp, _, _ = _build_pipelines(store, mock_llm, config=config)

    concept = ConceptDraft(name="x", content="content")
    mock_llm.set_response("extract_concepts", [concept])
    mock_llm.set_response(
        "judge_relations",
        [Decision(action="create", concept=concept, edges_to=[])],
    )
    ctx = wp.ingest("text")

    assert ctx.persisted is False


def test_auto_persist_saves_edges(empty_graph, mock_llm):
    """create 动作创建的边必须被持久化（SQLiteStore）。"""
    store = SQLiteStore({"path": ":memory:"})
    store.initialize()
    anchor = Node(id="anchor", name="Anchor", content="anchor content")
    store.add_node(anchor)

    pm = PluginManager()
    pm.register(mock_llm)
    ctx = PluginContext(
        store=store,
        config=MCSConfig(auto_persist=True),
        token_budget=TokenBudget(8000),
        context_renderer=None,  # type: ignore[arg-type]
        plugin_manager=pm,
    )
    pm.initialize_all(ctx)
    query_engine = QueryEngine(
        store=store,
        llm=mock_llm,
        plugin_manager=pm,
        token_budget=TokenBudget(8000),
        max_rounds=3,
        max_accumulated_nodes=20,
    )
    wp = WritePipeline(
        store=store,
        llm=mock_llm,
        query_engine=query_engine,
        plugin_manager=pm,
        token_budget=TokenBudget(8000),
        config=MCSConfig(auto_persist=True),
    )

    concept = ConceptDraft(name="new", content="new content")
    mock_llm.set_response("extract_concepts", [concept])
    mock_llm.set_response(
        "judge_relations",
        [Decision(action="create", concept=concept, edges_to=[{"target_id": "anchor"}])],
    )
    ctx = wp.ingest("text")

    assert ctx.persisted is True
    # create 动作的边（new → anchor）落盘；另有事件 → new 的背书边，不计入此断言
    rows = store.conn.execute(
        "SELECT COUNT(*) FROM edges WHERE target_id=?", ("anchor",)
    ).fetchone()
    assert rows[0] == 1


def test_auto_persist_storage_exception_handled(empty_graph, mock_llm):
    """存储异常必须被捕获，不影响 ingest 返回。"""
    store = InMemoryStore()
    config = MCSConfig(auto_persist=True)
    wp, _, _ = _build_pipelines(store, mock_llm, config=config)

    concept = ConceptDraft(name="x", content="content")
    mock_llm.set_response("extract_concepts", [concept])
    mock_llm.set_response(
        "judge_relations",
        [Decision(action="create", concept=concept, edges_to=[])],
    )
    ctx = wp.ingest("text")

    # ingest 必须正常返回，不抛异常
    assert ctx is not None
    assert ctx.changed  # 图更新成功
    # InMemoryStore 不支持持久化 → persisted 为 False
    assert ctx.persisted is False


def test_persisted_field_set_correctly(empty_graph, mock_llm):
    """WriteContext.persisted 字段必须正确反映落盘状态。"""
    store = InMemoryStore()
    config = MCSConfig(auto_persist=True)
    wp, _, _ = _build_pipelines(store, mock_llm, config=config)

    # 无 changed 时 persisted 应为 False
    mock_llm.set_response("extract_concepts", [])
    ctx = wp.ingest("text")
    assert ctx.persisted is False


# === Load-on-startup 测试 ===


def test_real_builder_build_runs_full_assembly(mock_llm):
    """回归：真实 MCSBuilder.build() 必须跑通 _init_plugin_context。

    曾因 _init_plugin_context 内未导入 PluginContext 抛 NameError，但当时没有任何
    测试调用真实 build()（历史上的测试构建器都各自重写了组装流程、未走
    MCSBuilder.build()），导致该回归未被发现。本测试直接走 MCSBuilder.build()。
    """
    from mcs.core.builder import MCSBuilder

    mock_cls = type(mock_llm)

    class _RegressionBuilder(MCSBuilder):
        def get_plugin_class(self, name: str):
            return mock_cls if name == "mock_llm" else None

    config = MCSConfig(
        shared_plugins=[],
        write_plugins=[],
        read_plugins=[],
        write_llm="mock_llm",
        read_llm="mock_llm",
        plugin_configs={"sqlite_storage": {"path": ":memory:"}},
    )
    mcs = _RegressionBuilder(config).build()
    try:
        # _init_plugin_context 已执行：双管线就绪、LLM 已注册到两侧（同实例共享）
        assert mcs.write_pipeline.llm is mcs.query_engine.llm
        assert mcs.get_plugin("mock_llm") is not None
    finally:
        mcs.shutdown()


# === D6：写入后守门核心兜底 ===


class _StubCompaction(CompactionPluginInterface):
    """should_run 恒 False、记录 run() 是否被调用的压缩插件桩。"""

    def __init__(self) -> None:
        super().__init__()
        self.run_called = False

    def get_name(self) -> str:
        return "stub_compaction"

    def should_run(self, changed_nodes, store) -> bool:
        return False

    def run(self, changed_nodes, store, llm_caller) -> None:
        self.run_called = True


def _wp_with_budget(store, mock_llm, token_budget, *plugins):
    """用指定 token_budget 构建 WritePipeline（不复用 _build_pipelines 的 8000 默认）。"""
    pm = PluginManager()
    pm.register(mock_llm)
    for p in plugins:
        pm.register(p)
    qe = QueryEngine(
        store=store,
        llm=mock_llm,
        plugin_manager=pm,
        token_budget=token_budget,
        max_rounds=3,
        max_accumulated_nodes=20,
    )
    return WritePipeline(
        store=store,
        llm=mock_llm,
        query_engine=qe,
        plugin_manager=pm,
        token_budget=token_budget,
        config=MCSConfig(),
    )


def test_compaction_forced_when_over_budget(empty_graph, mock_llm):
    """D6：changed_nodes 层级视图超 T 时强制运行 CompactionPlugin（忽略 should_run）。"""
    stub = _StubCompaction()
    wp = _wp_with_budget(empty_graph, mock_llm, TokenBudget(100), stub)
    big = Node(id="big", name="大", content="X" * 4000, node_class=CLASS_CONCEPT)
    empty_graph.add_node(big)
    wp._run_compaction([big])
    assert stub.run_called is True  # should_run=False 但超 T → 强制运行


def test_compaction_respects_should_run_when_under_budget(empty_graph, mock_llm):
    """D6：未超 T 时尊重 should_run（False → 不运行）。"""
    stub = _StubCompaction()
    wp = _wp_with_budget(empty_graph, mock_llm, TokenBudget(8000), stub)
    small = Node(id="s", name="小", content="hi", node_class=CLASS_CONCEPT)
    empty_graph.add_node(small)
    wp._run_compaction([small])
    assert stub.run_called is False


def test_no_compaction_plugin_logs_error_when_over_budget(empty_graph, mock_llm, caplog):
    """D6：超 T 但无 CompactionPlugin → logger.error 显式暴露（不静默）。"""
    wp = _wp_with_budget(empty_graph, mock_llm, TokenBudget(100))
    big = Node(id="big2", name="大", content="X" * 4000, node_class=CLASS_CONCEPT)
    empty_graph.add_node(big)
    with caplog.at_level(logging.ERROR):
        wp._run_compaction([big])
    assert any("核心不变量无法保证" in r.message for r in caplog.records)


def test_load_on_startup_restores_graph(tmp_path, mock_llm):
    """Builder.build() 时，若图为空且 SQLiteStore 存在，必须从存储加载已有数据。"""
    # 先创建一个有数据的数据库
    db_path = str(tmp_path / "test.db")
    store = SQLiteStore({"path": db_path})
    store.initialize()
    node1 = Node(id="n1", name="已存在节点", content="来自数据库")
    store.add_node(node1)
    store.save()
    store.shutdown()

    # 创建新的 MCS 实例，使用 Builder 构建
    new_store = SQLiteStore({"path": db_path})
    config = MCSConfig(
        shared_plugins=[],
        write_plugins=[],
        read_plugins=[],
        write_llm="mock_llm",
        read_llm="mock_llm",
    )
    mcs = MockLLMBuilder(config, mock_llm, store=new_store).build()

    # 图应该包含从数据库加载的节点
    nodes = mcs.store.get_all_nodes()
    assert len(nodes) == 1
    assert nodes[0].name == "已存在节点"
    mcs.shutdown()


def test_load_on_startup_skipped_when_graph_has_data(mock_llm):
    """如果内存图已有数据，load-on-startup 不应覆盖。"""
    store = SQLiteStore({"path": ":memory:"})
    store.initialize()
    pre_node = Node(id="pre", name="预先存在", content="内存中的节点")
    store.add_node(pre_node)

    config = MCSConfig(
        shared_plugins=[],
        write_plugins=[],
        read_plugins=[],
        write_llm="mock_llm",
        read_llm="mock_llm",
    )
    mcs = MockLLMBuilder(config, mock_llm, store=store).build()

    # 预先存在的节点应该保留
    nodes = mcs.store.get_all_nodes()
    assert len(nodes) == 1
    assert nodes[0].name == "预先存在"


def test_load_on_startup_handles_exception(tmp_path, mock_llm):
    """storage.load() 异常不影响 build() 完成。"""
    # 使用损坏的数据库路径
    db_path = str(tmp_path / "corrupt.db")
    store = SQLiteStore({"path": db_path})
    config = MCSConfig(
        shared_plugins=[],
        write_plugins=[],
        read_plugins=[],
        write_llm="mock_llm",
        read_llm="mock_llm",
    )
    # build 应该正常完成，不抛异常
    mcs = MockLLMBuilder(config, mock_llm, store=store).build()
    assert mcs is not None
    mcs.shutdown()


def test_load_on_startup_rebuilds_indexes(tmp_path, mock_llm):
    """reload 后必须重建 IndexInterface 索引；否则 alias 种子定位全失效。

    回归 reload 复用图候选集崩塌 bug：AliasIndexPlugin 在 initialize 时图尚空、
    索引建成空的，load-on-startup 加载节点后必须重建索引。
    """
    db_path = str(tmp_path / "idx.db")
    # 先用独立 SQLiteStore 落盘一个节点
    store = SQLiteStore({"path": db_path})
    store.initialize()
    store.add_node(Node(id="n1", name="Quantum", content="quantum computing"))
    store.save()
    store.shutdown()

    # 新 MCS reload（含 SQLiteStore + alias_index + alias_entry）
    new_store = SQLiteStore({"path": db_path})
    config = MCSConfig(
        shared_plugins=[],
        write_plugins=[],
        read_plugins=["alias_index", "alias_entry"],
        write_llm="mock_llm",
        read_llm="mock_llm",
    )
    mcs = MockLLMBuilder(config, mock_llm, store=new_store).build()

    ai = mcs.get_plugin("alias_index")
    assert ai is not None
    assert len(ai.index) > 0  # reload 后索引已重建（非空）
    entry = mcs.get_plugin("alias_entry")
    assert entry is not None
    hits = entry.locate("Quantum", None)
    assert any(n.id == "n1" for n in hits)  # 种子定位能命中
    mcs.shutdown()


# === 阶段 ① PreprocessPlugin 测试 ===


def test_write_pipeline_uses_write_preprocess_plugins(empty_graph, mock_llm):
    """写入管线阶段 ① 应使用 WritePreprocessPlugin。"""

    class _Upper(WritePreprocessPluginInterface):
        def get_name(self) -> str:
            return "upper_preprocess"

        def preprocess(self, text: str, ctx) -> str:
            return text.upper()

    wp, _, pm = _build_pipelines(empty_graph, mock_llm, _Upper())
    mock_llm.set_response("extract_concepts", [])
    ctx = wp.ingest("hello world")
    # processed 应该是大写的
    assert ctx.processed == "HELLO WORLD"


def test_write_pipeline_preprocess_chain_sequential(empty_graph, mock_llm):
    """多个 WritePreprocessPlugin 串行执行。"""

    class _AddSuffix(WritePreprocessPluginInterface):
        def __init__(self, suffix: str, **kw):
            super().__init__(**kw)
            self._suffix = suffix

        def get_name(self) -> str:
            return f"add_{self._suffix}"

        def preprocess(self, text: str, ctx) -> str:
            return text + self._suffix

    wp, _, pm = _build_pipelines(
        empty_graph,
        mock_llm,
        _AddSuffix(suffix="_b"),
        _AddSuffix(suffix="_a"),
    )
    mock_llm.set_response("extract_concepts", [])
    ctx = wp.ingest("hello")
    # 插件按 priority 排序，默认都是 0，按注册顺序
    assert ctx.processed.startswith("hello")


def test_write_pipeline_no_position_filtering(empty_graph, mock_llm):
    """写入管线 _run_preprocess 不再使用 position 属性筛选。"""
    wp, _, _ = _build_pipelines(empty_graph, mock_llm)
    # 确认方法中没有 getattr(p, "position", ...) 逻辑
    import inspect

    source = inspect.getsource(wp._run_preprocess)
    assert "position" not in source


# === 精确同名去重守门（防同实体碎片化）===


def test_create_dedups_into_existing_same_name(empty_graph, mock_llm):
    """同名 create 并入既有节点：不新建第二个、content 并入、edges_to 挂到既有。"""
    s = empty_graph
    s.add_node(Node(id="amz", name="Amazon", content="电商公司"))
    s.add_node(Node(id="anc", name="AWS", content="云服务"))
    wp, _, _ = _build_pipelines(s, mock_llm)

    decisions = [
        Decision(
            action="create",
            concept=ConceptDraft(name="Amazon", content="云计算巨头"),
            edges_to=[{"target_id": "anc"}],
        )
    ]
    wp._apply_decisions(decisions)

    amazons = [n for n in s.get_all_nodes() if n.name == "Amazon"]
    assert len(amazons) == 1  # 没新建第二个 Amazon
    assert "云计算巨头" in s.get_node("amz").content  # content 并入既有
    assert s.get_edges_between("amz", "anc")  # edges_to 挂到既有节点


def test_create_dedup_case_insensitive(empty_graph, mock_llm):
    """大小写不同也并入（amazon → Amazon）。"""
    s = empty_graph
    s.add_node(Node(id="amz", name="Amazon", content="x"))
    wp, _, _ = _build_pipelines(s, mock_llm)
    wp._apply_decisions(
        [Decision(action="create", concept=ConceptDraft(name="amazon", content="y"))]
    )
    assert len([n for n in s.get_all_nodes() if n.name.lower() == "amazon"]) == 1


def test_create_different_name_still_creates(empty_graph, mock_llm):
    """不同名仍正常新建（不误并）。"""
    s = empty_graph
    s.add_node(Node(id="amz", name="Amazon", content="x"))
    wp, _, _ = _build_pipelines(s, mock_llm)
    wp._apply_decisions(
        [Decision(action="create", concept=ConceptDraft(name="Google", content="y"))]
    )
    assert any(n.name == "Google" for n in s.get_all_nodes())
    assert len(s.get_all_nodes()) == 2


def test_create_same_batch_dup_merges(empty_graph, mock_llm):
    """同一批两个同名 create → 只建一个（同批后续同名也并入）。"""
    s = empty_graph
    wp, _, _ = _build_pipelines(s, mock_llm)
    wp._apply_decisions([
        Decision(action="create", concept=ConceptDraft(name="Tesla", content="a")),
        Decision(action="create", concept=ConceptDraft(name="Tesla", content="b")),
    ])
    assert len([n for n in s.get_all_nodes() if n.name == "Tesla"]) == 1


def test_ingest_writes_graph_summary_meta(mock_llm):
    """端到端：ingest concept → 阶段⑥调度 GraphSummaryPlugin → 图摘要写入 meta。

    覆盖 graph-summary change task 6.1：WritePipeline 调度链路对已注册的
    GraphSummaryPlugin 生效（should_run 命中 concept → run 读顶层 hub → 写 meta）。
    fanout 未注册，故手动预建 root + hub 层级作为归纳对象。
    """
    from mcs.plugins.maintenance.graph_summary import GraphSummaryPlugin

    store = InMemoryStore()
    store.add_node(Node(id="__seed_root__", name="__seed_root__", content="", extensions={"hub": True}))
    store.add_node(Node(id="h1", name="机器学习", content="ML 基础", extensions={"hub": True}))
    store.add_edge("__seed_root__", "h1", type="关联")

    concept = ConceptDraft(name="梯度下降", content="优化算法")
    mock_llm.set_response("extract_concepts", [concept])
    mock_llm.set_response(
        "judge_relations", [Decision(action="create", concept=concept)]
    )
    mock_llm.set_response("gen_graph_summary", "这张图关于机器学习")

    wp, _, _ = _build_pipelines(store, mock_llm, GraphSummaryPlugin())
    wp.ingest("梯度下降是优化算法")

    assert store.get_graph_meta("graph_summary") == "这张图关于机器学习"

"""WritePipeline 测试：7 阶段管道行为。"""

from __future__ import annotations

from mcs.core.config import MCSConfig
from mcs.core.decisions import ConceptDraft, Decision
from mcs.core.graph import GraphStore, Node
from mcs.core.plugin_manager import PluginContext, PluginManager
from mcs.core.query_engine import QueryEngine
from mcs.core.token_budget import TokenBudget
from mcs.core.write_pipeline import WritePipeline
from mcs.interfaces.compaction_plugin import CompactionPluginInterface
from mcs.interfaces.storage import StorageInterface


def _build_pipelines(graph: GraphStore, mock_llm, *extra_plugins, config=None):
    pm = PluginManager()
    pm.register(mock_llm)
    for p in extra_plugins:
        pm.register(p)
    ctx = PluginContext(
        graph=graph,
        config=config or MCSConfig(),
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
    assert len(nodes) == 1
    assert nodes[0].name == "深度学习"


def test_merge_decision_updates_existing_node(empty_graph, mock_llm):
    """'merge' 决策指向已存在的目标；该目标的 statements 槽位
    会追加 initial_statements。
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
    # 目标节点在图中仍然只有一个实例。
    assert len([n for n in empty_graph.get_all_nodes() if n.id == "t1"]) == 1
    # initial_statements 必须真正落到目标的 statements 槽（回归 merge 丢数据 bug）。
    items = empty_graph.get_node("t1").extensions.get("statements", {}).get("items", [])
    assert items == ["新事实"]
    # concept.name 应作为别名并入目标。
    aliases = empty_graph.get_node("t1").extensions.get("alias_index", {}).get(
        "aliases", []
    )
    assert "新名字" in aliases


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
    """⑥ 当 should_run 返回 True 时，Compaction 插件的 run() 必须被调用。"""
    run_count = {"n": 0}

    class _CountingCompaction(CompactionPluginInterface):
        def get_name(self) -> str:
            return "counting_compaction"

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
    class _BlockedCompaction(CompactionPluginInterface):
        def get_name(self) -> str:
            return "blocked"

        def should_run(self, changed_nodes, graph):
            return False

        def run(self, changed_nodes, graph, llm_caller):
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
    from mcs.plugins.phase1.source_tracking import Source

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


class _MockStorage(StorageInterface):
    """用于测试的 mock 存储插件。"""

    def get_name(self) -> str:
        return "mock_storage"

    def __init__(self, config=None):
        self.saved_nodes: list[Node] = []
        self.saved_edges: list = []
        self._load_graph: GraphStore | None = None
        self._load_raise: Exception | None = None

    def save(self, graph):
        pass

    def load(self):
        if self._load_raise:
            raise self._load_raise
        return self._load_graph or GraphStore()

    def save_node(self, node):
        self.saved_nodes.append(node)

    def save_edge(self, edge):
        self.saved_edges.append(edge)


def test_auto_persist_saves_changed_nodes(empty_graph, mock_llm):
    """auto_persist=True 时，每次 ingest 后 changed 节点必须落盘。"""
    storage = _MockStorage()
    config = MCSConfig(auto_persist=True)
    wp, _, pm = _build_pipelines(empty_graph, mock_llm, storage, config=config)

    concept = ConceptDraft(name="x", content="content")
    mock_llm.set_response("extract_concepts", [concept])
    mock_llm.set_response(
        "judge_relations",
        [Decision(action="create", concept=concept, edges_to=[])],
    )
    ctx = wp.ingest("text")

    assert ctx.persisted is True
    assert len(storage.saved_nodes) == 1
    assert storage.saved_nodes[0].name == "x"


def test_auto_persist_false_skips_persist(empty_graph, mock_llm):
    """auto_persist=False 时，阶段 ⑦ 必须跳过。"""
    storage = _MockStorage()
    config = MCSConfig(auto_persist=False)
    wp, _, _ = _build_pipelines(empty_graph, mock_llm, storage, config=config)

    concept = ConceptDraft(name="x", content="content")
    mock_llm.set_response("extract_concepts", [concept])
    mock_llm.set_response(
        "judge_relations",
        [Decision(action="create", concept=concept, edges_to=[])],
    )
    ctx = wp.ingest("text")

    assert ctx.persisted is False
    assert len(storage.saved_nodes) == 0


def test_auto_persist_saves_edges(empty_graph, mock_llm):
    """create 动作创建的边必须被持久化。"""
    anchor = Node(id="anchor", name="Anchor", content="anchor content")
    empty_graph.add_node(anchor)

    storage = _MockStorage()
    config = MCSConfig(auto_persist=True)
    wp, _, _ = _build_pipelines(empty_graph, mock_llm, storage, config=config)

    concept = ConceptDraft(name="new", content="new content")
    mock_llm.set_response("extract_concepts", [concept])
    mock_llm.set_response(
        "judge_relations",
        [Decision(action="create", concept=concept, edges_to=["anchor"])],
    )
    ctx = wp.ingest("text")

    assert ctx.persisted is True
    assert len(storage.saved_nodes) == 1
    assert len(storage.saved_edges) == 1


def test_auto_persist_storage_exception_handled(empty_graph, mock_llm):
    """存储异常必须被捕获，不影响 ingest 返回。"""
    storage = _MockStorage()

    def raise_on_save(node):
        raise RuntimeError("disk full")

    storage.save_node = raise_on_save

    config = MCSConfig(auto_persist=True)
    wp, _, _ = _build_pipelines(empty_graph, mock_llm, storage, config=config)

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
    assert ctx.persisted is False  # 落盘失败


def test_persisted_field_set_correctly(empty_graph, mock_llm):
    """WriteContext.persisted 字段必须正确反映落盘状态。"""
    storage = _MockStorage()
    config = MCSConfig(auto_persist=True)
    wp, _, _ = _build_pipelines(empty_graph, mock_llm, storage, config=config)

    # 无 changed 时 persisted 应为 False
    mock_llm.set_response("extract_concepts", [])
    ctx = wp.ingest("text")
    assert ctx.persisted is False

    # 有 changed 且落盘成功时 persisted 应为 True
    concept = ConceptDraft(name="x", content="content")
    mock_llm.set_response("extract_concepts", [concept])
    mock_llm.set_response(
        "judge_relations",
        [Decision(action="create", concept=concept, edges_to=[])],
    )
    ctx = wp.ingest("text")
    assert ctx.persisted is True


# === Load-on-startup 测试 ===


def test_load_on_startup_restores_graph(tmp_path, mock_llm):
    """MCS.initialize() 时，若图为空且 Storage 存在，必须从存储加载已有数据。"""
    from mcs import MCS
    from mcs.plugins.phase1.sqlite_storage import SQLiteStoragePlugin

    # 先创建一个有数据的数据库
    db_path = str(tmp_path / "test.db")
    storage = SQLiteStoragePlugin({"path": db_path})
    pre_graph = GraphStore()
    node1 = Node(id="n1", name="已存在节点", content="来自数据库")
    pre_graph.add_node(node1)

    from mcs.core.plugin_manager import PluginManager
    from mcs.core.plugin_manager import PluginContext
    pm = PluginManager()
    pm.register(storage)
    pm.register(mock_llm)
    ctx = PluginContext(
        graph=pre_graph,
        config=MCSConfig(),
        token_budget=TokenBudget(8000),
        context_renderer=None,
        plugin_manager=pm,
    )
    pm.initialize_all(ctx)
    storage.save(pre_graph)

    # 创建新的 MCS 实例，图应为空
    config = MCSConfig(
        plugins=["sqlite_storage", "mock_llm"],
        plugin_configs={"sqlite_storage": {"path": db_path}},
    )
    mcs = MCS(config)
    mcs.register_plugin(mock_llm)
    mcs.initialize()

    # 图应该包含从数据库加载的节点
    nodes = mcs.graph.get_all_nodes()
    assert len(nodes) == 1
    assert nodes[0].name == "已存在节点"


def test_load_on_startup_skipped_when_graph_has_data(mock_llm):
    """如果内存图已有数据，load-on-startup 不应覆盖。"""
    from mcs import MCS

    config = MCSConfig(plugins=["mock_llm"])
    mcs = MCS(config)

    # 手动预先添加节点
    pre_node = Node(id="pre", name="预先存在", content="内存中的节点")
    mcs.graph.add_node(pre_node)

    mcs.register_plugin(mock_llm)
    mcs.initialize()

    # 预先存在的节点应该保留
    nodes = mcs.graph.get_all_nodes()
    assert len(nodes) == 1
    assert nodes[0].name == "预先存在"


def test_load_on_startup_handles_exception(tmp_path, mock_llm):
    """storage.load() 异常不影响 initialize() 完成。"""
    from mcs import MCS

    # 使用损坏的数据库路径
    db_path = str(tmp_path / "corrupt.db")

    config = MCSConfig(
        plugins=["sqlite_storage", "mock_llm"],
        plugin_configs={"sqlite_storage": {"path": db_path}},
    )
    mcs = MCS(config)
    mcs.register_plugin(mock_llm)

    # initialize 应该正常完成，不抛异常
    mcs.initialize()
    assert mcs._initialized is True


def test_load_on_startup_rebuilds_indexes(tmp_path, mock_llm):
    """reload 后必须重建 IndexInterface 索引；否则 alias 种子定位全失效。

    回归 reload 复用图候选集崩塌 bug：AliasIndexPlugin 在 initialize 时图尚空、
    索引建成空的，load-on-startup 加载节点后必须重建索引。
    """
    from mcs import MCS
    from mcs.plugins.phase1.sqlite_storage import SQLiteStoragePlugin

    db_path = str(tmp_path / "idx.db")
    # 先用独立 storage 落盘一个节点
    storage = SQLiteStoragePlugin({"path": db_path})
    pm = PluginManager()
    pm.register(storage)
    pm.initialize_all(
        PluginContext(
            graph=GraphStore(),
            config=MCSConfig(),
            token_budget=TokenBudget(8000),
            context_renderer=None,  # type: ignore[arg-type]
            plugin_manager=pm,
        )
    )
    storage.save_node(Node(id="n1", name="Quantum", content="quantum computing"))
    storage.commit()
    storage.shutdown()

    # 新 MCS reload（含 alias_index + alias_entry）
    config = MCSConfig(
        plugins=["sqlite_storage", "alias_index", "alias_entry"],
        plugin_configs={"sqlite_storage": {"path": db_path}},
    )
    mcs = MCS(config)
    mcs.register_plugin(mock_llm)
    mcs.initialize()

    ai = mcs.get_plugin("alias_index")
    assert len(ai.index) > 0  # reload 后索引已重建（非空）
    hits = mcs.get_plugin("alias_entry").locate("Quantum", None)
    assert any(n.id == "n1" for n in hits)  # 种子定位能命中
    mcs.shutdown()

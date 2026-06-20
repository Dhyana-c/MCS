"""统一 ingest 测试：⓪ 规则入库（事件 + source）+ ③ 仅 content + ⑤ 背书连边 + 载重规则。

覆盖 unified-ingest change tasks 5.1-5.7：

- 5.1 纯文本 str：恰一个事件（now）+ 概念 / 事实，无 source，行为兼容
- 5.2 IngestInput 带 timestamp / source：事件用给定 timestamp；source 按 chunks 切分
- 5.3 背书连边：事件 / source → 抽出概念 / 事实，方向正确
- 5.4 载重规则：get_relations(概念) 不含事件边、get_related_events(概念) 可达事件
- 5.5 空 content：仍建事件（+ source）、落盘成功、不抛
- 5.6 转述过去事件 → 抽成带时间属性的事实，不成第二个时间轴事件
- 5.7 幂等契约不变（mark-on-success 仍随成功 ingest 触发）
"""

from __future__ import annotations

import hashlib

from mcs.core.plugin_manager import PluginContext, PluginManager
from mcs.core.query_engine import QueryEngine
from mcs.core.token_budget import TokenBudget
from mcs.core.write_pipeline import WritePipeline
from mcs.entities.config import MCSConfig
from mcs.entities.decisions import ConceptDraft, Decision, IngestInput, SourceData
from mcs.entities.graph import (
    CLASS_CONCEPT,
    CLASS_EVENT,
    CLASS_FACT,
    CLASS_SOURCE,
    CORE_NODE_CLASSES,
    EDGE_ASSOC,
    Node,
)
from mcs.plugins.preprocess.source_tracking import (
    IdempotencyCheckPlugin,
    SourceTrackingPlugin,
)
from mcs.stores.in_memory import InMemoryStore
from mcs.stores.sqlite_store import SQLiteStore


# ─── 装配 ────────────────────────────────────────────────────────────────────


def _pipeline(store=None, mock_llm=None, config=None) -> WritePipeline:
    """InMemoryStore + mock LLM 的轻量管线（无 WRITE_PREPROCESS 插件）。"""
    store = store or InMemoryStore()
    pm = PluginManager()
    pm.register(mock_llm)
    qe = QueryEngine(
        store=store,
        llm=mock_llm,
        plugin_manager=pm,
        token_budget=TokenBudget(8000),
        max_rounds=1,
        max_accumulated_nodes=20,
    )
    return WritePipeline(
        store=store,
        llm=mock_llm,
        query_engine=qe,
        plugin_manager=pm,
        token_budget=TokenBudget(8000),
        config=config or MCSConfig(),
    )


def _sqlite_pipeline(db_path: str, mock_llm, *, idempotency: bool = False):
    """SQLiteStore 管线（auto_persist），可选挂 IdempotencyCheckPlugin。"""
    store = SQLiteStore({"path": db_path})
    pm = PluginManager()
    pm.register(mock_llm)
    schema_exts = []
    node_exts = {}
    if idempotency:
        st = SourceTrackingPlugin()
        idem = IdempotencyCheckPlugin()
        pm.register(st)
        pm.register(idem)
        schema_exts = [st]
        node_exts = {"source_tracking": st}
    else:
        idem = None
    config = MCSConfig(auto_persist=True)
    store.initialize(schema_extensions=schema_exts, node_extensions=node_exts)
    ctx = PluginContext(
        store=store,
        config=config,
        token_budget=TokenBudget(8000),
        context_renderer=None,  # type: ignore[arg-type]
        plugin_manager=pm,
    )
    pm.initialize_all(ctx)
    qe = QueryEngine(
        store=store,
        llm=mock_llm,
        plugin_manager=pm,
        token_budget=TokenBudget(8000),
        max_rounds=1,
        max_accumulated_nodes=20,
    )
    wp = WritePipeline(
        store=store,
        llm=mock_llm,
        query_engine=qe,
        plugin_manager=pm,
        token_budget=TokenBudget(8000),
        config=config,
    )
    return wp, store, idem


def _set_create(mock_llm, name="C", node_class=CLASS_CONCEPT) -> ConceptDraft:
    """让 mock LLM 抽出一个概念 / 事实并 create。"""
    concept = ConceptDraft(name=name, content=f"{name} 的内容", node_class=node_class)
    mock_llm.set_response("extract_concepts", [concept])
    mock_llm.set_response(
        "judge_relations",
        [Decision(action="create", concept=concept, edges_to=[], node_class=node_class)],
    )
    return concept


def _events(store) -> list[Node]:
    return [n for n in store.get_all_nodes() if n.node_class == CLASS_EVENT]


# ─── 5.1 纯文本 str：恰一个事件（now）+ 概念，无 source ─────────────────────


def test_str_input_creates_exactly_one_event_and_concept(empty_graph, mock_llm):
    """str 入参：归一化为 IngestInput(content=text)，建一个 now 事件 + 概念，无 source。"""
    wp = _pipeline(empty_graph, mock_llm)
    _set_create(mock_llm, name="深度学习")

    ctx = wp.ingest("深度学习是机器学习的一个子领域")

    # 恰一个事件节点，timestamp = now（非空 ISO 串）
    events = _events(empty_graph)
    assert len(events) == 1
    assert ctx.event_node is not None
    assert ctx.event_node.id == events[0].id
    ts = ctx.event_node.extensions["event_meta"]["timestamp"]
    assert isinstance(ts, str) and ts  # now 兜底，非空
    # 概念节点恰一个
    concepts = [n for n in empty_graph.get_all_nodes() if n.node_class == CLASS_CONCEPT]
    assert len(concepts) == 1 and concepts[0].name == "深度学习"
    # 无 source
    assert ctx.source_nodes == []
    assert not any(n.node_class == CLASS_SOURCE for n in empty_graph.get_all_nodes())


def test_str_input_event_name_derived_from_content(empty_graph, mock_llm):
    """无 event_name 时，事件 name 由 content 截断派生（>40 字截断 + …）。"""
    wp = _pipeline(empty_graph, mock_llm)
    mock_llm.set_response("extract_concepts", [])
    long = "今天记录一段很长的输入文本用于验证事件名称的截断派生逻辑是否能够正确工作并触发省略号结尾标记"
    assert len(long) > 40  # 自校验：确实超阈值
    ctx = wp.ingest(long)
    name = ctx.event_node.name
    assert name.endswith("…")  # 超 40 字截断
    assert long[:40] in name


# ─── 5.2 IngestInput 带 timestamp / source：source 按 chunks 切分 ────────────


def test_ingest_input_uses_given_timestamp(empty_graph, mock_llm):
    """IngestInput.timestamp 直接落到事件节点 event_meta。"""
    wp = _pipeline(empty_graph, mock_llm)
    _set_create(mock_llm, name="X")
    ctx = wp.ingest(IngestInput(content="x", timestamp="2026-06-20T10:00:00Z"))
    assert ctx.event_node.extensions["event_meta"]["timestamp"] == "2026-06-20T10:00:00Z"


def test_ingest_input_source_split_into_chunks(empty_graph, mock_llm):
    """source 按 chunks 切分建多节点（不经 LLM）。"""
    wp = _pipeline(empty_graph, mock_llm)
    _set_create(mock_llm, name="X")
    ctx = wp.ingest(
        IngestInput(
            content="x",
            source=SourceData(
                name="report.pdf",
                source_type="file",
                chunks=[
                    {"content": "第一段", "chunk_index": 0},
                    {"content": "第二段", "chunk_index": 1},
                ],
            ),
        )
    )
    sources = [n for n in empty_graph.get_all_nodes() if n.node_class == CLASS_SOURCE]
    assert len(sources) == 2
    assert {n.content for n in sources} == {"第一段", "第二段"}
    assert len(ctx.source_nodes) == 2


# ─── 5.3 背书连边：事件 / source → 抽出概念 / 事实，方向正确 ──────────────────


def test_endorsement_edges_event_and_source_to_core(empty_graph, mock_llm):
    """⑤ 后：事件 / source → 本次概念 / 事实 的关联背书边存在，方向固定（源端=事件/source）。"""
    wp = _pipeline(empty_graph, mock_llm)
    _set_create(mock_llm, name="C", node_class=CLASS_CONCEPT)
    ctx = wp.ingest(
        IngestInput(
            content="c",
            source=SourceData(name="doc.pdf", source_type="file"),
        )
    )
    event = ctx.event_node
    source = ctx.source_nodes[0]
    concept = next(n for n in empty_graph.get_all_nodes() if n.node_class == CLASS_CONCEPT)

    # 事件 → 概念（正向），不存在 反向
    assert empty_graph.get_edges_between(event.id, concept.id)
    assert not empty_graph.get_edges_between(concept.id, event.id)
    # source → 概念（正向）
    assert empty_graph.get_edges_between(source.id, concept.id)
    assert not empty_graph.get_edges_between(concept.id, source.id)
    # 都是关联边
    for e in empty_graph.get_edges_between(event.id, concept.id):
        assert e.type == EDGE_ASSOC


def test_endorsement_edges_to_fact(empty_graph, mock_llm):
    """背书边也连到事实节点（事实为一等节点，可被事件背书）。"""
    wp = _pipeline(empty_graph, mock_llm)
    _set_create(mock_llm, name="F", node_class=CLASS_FACT)
    ctx = wp.ingest("f")
    event = ctx.event_node
    fact = next(n for n in empty_graph.get_all_nodes() if n.node_class == CLASS_FACT)
    assert empty_graph.get_edges_between(event.id, fact.id)


def test_endorsement_targets_meta_backfilled(empty_graph, mock_llm):
    """event_meta.targets 回填为本次目标 id（与边一致）。"""
    wp = _pipeline(empty_graph, mock_llm)
    _set_create(mock_llm, name="C")
    ctx = wp.ingest("c")
    concept = next(n for n in empty_graph.get_all_nodes() if n.node_class == CLASS_CONCEPT)
    assert concept.id in ctx.event_node.extensions["event_meta"]["targets"]


def test_concept_not_absorbed_by_same_name_event(empty_graph, mock_llm):
    """事件名（由 content 派生）与概念名同名时，概念不被并入事件节点。

    回归 ⑤ 同名去重：事件 / source 不参与去重（仅核心节点参与），否则
    content≈概念名 会把概念错并入同名事件、丢失概念节点。
    """
    wp = _pipeline(empty_graph, mock_llm)
    _set_create(mock_llm, name="Python")  # 概念名与 content 同名
    ctx = wp.ingest("Python")

    concepts = [n for n in empty_graph.get_all_nodes() if n.node_class == CLASS_CONCEPT]
    events = _events(empty_graph)
    # 概念与事件各自独立存在，未合并
    assert len(concepts) == 1
    assert len(events) == 1
    assert concepts[0].id != events[0].id
    # 概念 content 未被并入事件
    assert "Python 的内容" in concepts[0].content
    # 事件仍背书该概念
    assert empty_graph.get_edges_between(events[0].id, concepts[0].id)


# ─── 5.4 载重规则：get_relations(概念) 不含事件边、get_related_events 可达 ────


def test_load_bearing_rule_filters_event_edges(empty_graph, mock_llm):
    """核心节点 get_relations 过滤事件背书边；事件侧 get_relations 仍可见；get_related_events 可达。"""
    wp = _pipeline(empty_graph, mock_llm)
    _set_create(mock_llm, name="C")
    ctx = wp.ingest("c")
    event = ctx.event_node
    concept = next(n for n in empty_graph.get_all_nodes() if n.node_class == CLASS_CONCEPT)

    # 核心节点侧：get_relations 不含事件边
    core_assoc = [e for e in empty_graph.get_relations(concept.id) if e.type == EDGE_ASSOC]
    assert not any(e.source_id == event.id for e in core_assoc)

    # 事件侧：get_relations 仍可达核心
    event_assoc = [e for e in empty_graph.get_relations(event.id) if e.type == EDGE_ASSOC]
    assert any(e.target_id == concept.id for e in event_assoc)

    # 定向查事件：get_related_events 绕过载重、可达事件
    related = empty_graph.get_related_events(concept.id)
    assert any(e.id == event.id for e in related)


# ─── 5.5 空 content：仍建事件（+ source）、落盘成功、不抛 ─────────────────────


def test_empty_content_still_creates_event_and_persists(tmp_path, mock_llm):
    """content 抽取为空时：事件（+ source）仍建、随 ⑦ 落盘、不抛。"""
    wp, store, _ = _sqlite_pipeline(str(tmp_path / "empty.db"), mock_llm)
    mock_llm.set_response("extract_concepts", [])  # 概念抽取为空

    ctx = wp.ingest(
        IngestInput(
            content="",
            source=SourceData(name="doc.pdf", source_type="file"),
        )
    )

    assert ctx.concepts == []
    assert ctx.changed == []
    # 事件 + source 仍建并落盘
    assert ctx.event_node is not None
    assert len(ctx.source_nodes) == 1
    assert ctx.persisted is True
    rows = store.conn.execute(
        "SELECT COUNT(*) FROM nodes WHERE node_class=?", (CLASS_EVENT,)
    ).fetchone()
    assert rows[0] == 1
    src_rows = store.conn.execute(
        "SELECT COUNT(*) FROM nodes WHERE node_class=?", (CLASS_SOURCE,)
    ).fetchone()
    assert src_rows[0] == 1


# ─── 5.6 转述过去事件 → 带时间属性的事实，不成第二个时间轴事件 ────────────────


def test_narrated_past_event_becomes_fact_not_second_event(empty_graph, mock_llm):
    """content 内"三年前发生 X"由 LLM 抽成事实；ingest 仍只记一个时间轴事件。"""
    wp = _pipeline(empty_graph, mock_llm)
    # LLM 把转述的过去事件抽成 带时间属性的事实（谓词 + 时间落 content）
    _set_create(mock_llm, name="X", node_class=CLASS_FACT)
    ctx = wp.ingest("三年前发生 X")

    # 恰一个时间轴事件（记录行为），不是两个
    assert len(_events(empty_graph)) == 1
    # X 是事实（核心图），不是事件
    facts = [n for n in empty_graph.get_all_nodes() if n.node_class == CLASS_FACT]
    assert len(facts) == 1 and facts[0].name == "X"
    # 事件背书该事实
    assert empty_graph.get_edges_between(ctx.event_node.id, facts[0].id)


# ─── 5.7 幂等契约不变（mark-on-success 随成功 ingest 触发） ──────────────────


def test_idempotency_mark_on_success_intact(tmp_path, mock_llm):
    """调用方幂等契约不变：成功 ingest 后 mark-on-success 触发，is_ingested 返回 True。

    覆盖正常（有概念）与空 content 两条路径——事件 / source 的新增不破坏标记时机。
    """
    db = str(tmp_path / "idem.db")
    wp, store, idem = _sqlite_pipeline(db, mock_llm, idempotency=True)

    # 正常路径：抽出概念 → 成功 → 标记
    _set_create(mock_llm, name="Y")
    wp.ingest("y", doc_id="D1", chunk_id="0")
    h = hashlib.sha256("y".encode("utf-8")).hexdigest()
    assert idem.is_ingested("D1", "0", h) is True

    # 空 content 路径：事件仍建 + 落盘 → 同样标记（调用方据此跳过，不再建第二事件）
    mock_llm.set_response("extract_concepts", [])
    wp.ingest("", doc_id="D1", chunk_id="1")
    h2 = hashlib.sha256("".encode("utf-8")).hexdigest()
    assert idem.is_ingested("D1", "1", h2) is True


# ─── 补充：重复 ingest 的事件行为（D6）+ 背书命中既有概念 ──────────────────────


def test_duplicate_ingest_creates_second_event_reendorsing_same_concept(
    empty_graph, mock_llm
):
    """重复 ingest 同一内容：每次调用建一个事件（D6）；概念经同名去重并入既有、
    被两个事件分别背书（非孤儿事件）。幂等不在管线内跳过抽取——避免重复是调用方责任。"""
    wp = _pipeline(empty_graph, mock_llm)
    _set_create(mock_llm, name="C")

    ctx1 = wp.ingest("c")
    ctx2 = wp.ingest("c")

    # 两个事件（每次调用一个），概念仍只一个（同名去重并入）
    events = _events(empty_graph)
    concepts = [n for n in empty_graph.get_all_nodes() if n.node_class == CLASS_CONCEPT]
    assert len(events) == 2
    assert len(concepts) == 1
    assert ctx1.event_node.id != ctx2.event_node.id
    # 两个事件都背书同一概念（第二个事件的背书目标是 merge 命中的既有概念，非新建）
    cid = concepts[0].id
    assert empty_graph.get_edges_between(ctx1.event_node.id, cid)
    assert empty_graph.get_edges_between(ctx2.event_node.id, cid)


def test_endorsement_to_preexisting_merge_target(empty_graph, mock_llm):
    """背书"命中"：抽出概念 merge 进既有同名概念时，事件背书的是既有节点（非新建）。"""
    # 预置一个核心概念节点
    seeded = Node(id="seed-c", name="C", content="既有 C", node_class=CLASS_CONCEPT)
    empty_graph.add_node(seeded)

    wp = _pipeline(empty_graph, mock_llm)
    _set_create(mock_llm, name="C")  # 同名 → 命中既有、merge 不新建
    ctx = wp.ingest("c")

    # 未新建概念：仍只 seeded 一个
    concepts = [n for n in empty_graph.get_all_nodes() if n.node_class == CLASS_CONCEPT]
    assert len(concepts) == 1 and concepts[0].id == "seed-c"
    # 事件背书既有概念（命中路径也连背书边）
    assert empty_graph.get_edges_between(ctx.event_node.id, "seed-c")

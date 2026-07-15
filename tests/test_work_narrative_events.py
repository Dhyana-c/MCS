"""work-narrative-events 测试：per-universe 事件层 + 作品叙事事件 LLM 抽取 + 叙事时间线。

覆盖 tasks §4（含边界）：
- 4.1 现实摄入事件规则产生（不调 LLM）/ 作品叙事事件 LLM 抽取（纪年 + 作品事件层）
- 4.2 叙事时间线按纪年升序（查询期组装、不落节点）
- 4.3 每 universe 独立时间轴（不互染）
- 4.4 作品纪年非 ISO 排序口径（数字年可排、"建安五年"垫底不抛）
- 4.5 get_related_events universe 过滤（None 全返保 mug 查出处；传参才过滤）
- 4.6 WorkEventDraft 与 EventData / ConceptDraft 语义边界
- 4.7 文本转述时间不盖用户时间轴
"""

from __future__ import annotations

import dataclasses

import pytest

from mcs.core.plugin_manager import PluginManager
from mcs.core.query_engine import QueryEngine
from mcs.core.token_budget import TokenBudget
from mcs.core.write_pipeline import WritePipeline
from mcs.entities.decisions import (
    ConceptDraft,
    Decision,
    EventData,
    IngestInput,
    WorkEventDraft,
)
from mcs.entities.graph import (
    CLASS_CONCEPT,
    CLASS_EVENT,
    EDGE_ASSOC,
    REALITY_UNIVERSE,
    Node,
)
from mcs.utils.timestamps import event_sort_key, timestamp_sort_value


def _make(store, mock_llm) -> tuple[WritePipeline, QueryEngine]:
    pm = PluginManager()
    pm.register(mock_llm)
    tb = TokenBudget(8000)
    qe = QueryEngine(store=store, llm=mock_llm, plugin_manager=pm, token_budget=tb)
    wp = WritePipeline(
        store=store, llm=mock_llm, query_engine=qe, plugin_manager=pm, token_budget=tb
    )
    return wp, qe


def _events(store, universe: str | None = None) -> list[Node]:
    evs = store.get_nodes_by_class(CLASS_EVENT)
    if universe is not None:
        evs = [e for e in evs if e.universe == universe]
    return evs


def _ts(node: Node) -> str | None:
    return ((node.extensions or {}).get("event_meta") or {}).get("timestamp")


# === 4.1 事件产生分流 ===


def test_reality_ingest_event_rule_made_no_llm(empty_graph, mock_llm) -> None:
    """现实摄入（无 work_id）：摄入事件规则产生、u=__reality__，不调作品事件抽取。"""
    wp, _ = _make(empty_graph, mock_llm)
    wp.ingest(IngestInput(content="今天天气不错", timestamp="2026-07-14T08:00:00"))
    evs = _events(empty_graph)
    assert len(evs) == 1
    assert evs[0].universe == REALITY_UNIVERSE
    assert _ts(evs[0]) == "2026-07-14T08:00:00"
    # 不经 LLM 产生摄入事件；且现实 ingest 不启用 extract_work_events
    purposes = [c["purpose"] for c in mock_llm.call_log]
    assert "extract_work_events" not in purposes


def test_work_ingest_extracts_narrative_events(empty_graph, mock_llm) -> None:
    """作品摄入（work_id 非空）：LLM 抽取叙事事件，u=work、timestamp=纪年、参与者背书。"""
    wp, _ = _make(empty_graph, mock_llm)
    mock_llm.set_response("extract_concepts", [
        ConceptDraft(name="曹操", content="东汉末年枭雄", node_class=CLASS_CONCEPT),
    ])
    mock_llm.set_response("judge_relations", [
        Decision(action="create", concept=ConceptDraft(name="曹操", content="东汉末年枭雄")),
    ])
    mock_llm.set_response("extract_work_events", [
        WorkEventDraft(
            name="曹操杀吕伯奢",
            content="曹操疑心误杀吕伯奢全家",
            narr_timestamp="200 年",
            participants=["曹操", "吕伯奢"],
        ),
    ])
    ctx = wp.ingest(IngestInput(content="200 年曹操杀吕伯奢……", work_id="三国演义"))

    # 抽取调用发生且带 work 上下文
    purposes = [c["purpose"] for c in mock_llm.call_log]
    assert "extract_work_events" in purposes
    call = next(c for c in mock_llm.call_log if c["purpose"] == "extract_work_events")
    assert call["free_args"]["work_id"] == "三国演义"

    # 作品事件层：u=work、纪年 timestamp
    work_evs = _events(empty_graph, "三国演义")
    assert len(work_evs) == 1
    ev = work_evs[0]
    assert ev.name == "曹操杀吕伯奢"
    assert _ts(ev) == "200 年"
    assert ctx.work_event_nodes == [ev]

    # 摄入行为事件仍固定现实（不随被读作品变）
    reality_evs = _events(empty_graph, REALITY_UNIVERSE)
    assert len(reality_evs) == 1

    # participants 解析：曹操命中同 universe 概念复用；吕伯奢未命中新建（u=work）
    names = {n.name: n for n in empty_graph.get_all_nodes()}
    assert names["吕伯奢"].universe == "三国演义"
    assert names["吕伯奢"].node_class == CLASS_CONCEPT
    cao = names["曹操"]
    targets = {e.target_id for e in empty_graph.get_all_edges()
               if e.source_id == ev.id and e.type == EDGE_ASSOC}
    assert targets == {cao.id, names["吕伯奢"].id}
    # 参与者 id 落 event_meta
    meta = (ev.extensions or {}).get("event_meta", {})
    assert set(meta.get("participants", [])) == targets


def test_work_ingest_participant_not_cross_universe(empty_graph, mock_llm) -> None:
    """参与者解析限同 universe：现实同名概念 MUST NOT 被作品事件复用/背书。"""
    empty_graph.add_node(Node(
        id="real_cao", name="曹操", content="正史曹操",
        node_class=CLASS_CONCEPT, universe=REALITY_UNIVERSE,
    ))
    wp, _ = _make(empty_graph, mock_llm)
    mock_llm.set_response("extract_work_events", [
        WorkEventDraft(name="杀吕伯奢", content="……", narr_timestamp="200 年",
                       participants=["曹操"]),
    ])
    wp.ingest(IngestInput(content="……", work_id="三国演义"))
    ev = _events(empty_graph, "三国演义")[0]
    endorsed = {e.target_id for e in empty_graph.get_all_edges()
                if e.source_id == ev.id and e.type == EDGE_ASSOC}
    # 未命中同 universe → 新建演义曹操（≠ real_cao）
    assert "real_cao" not in endorsed
    assert len(endorsed) == 1
    new_cao = empty_graph.get_node(next(iter(endorsed)))
    assert new_cao.universe == "三国演义" and new_cao.name == "曹操"


def test_work_events_only_when_llm_returns_empty(empty_graph, mock_llm) -> None:
    """作品摄入但 LLM 抽不出事件（返回 []）：不产作品事件、不由规则兜底产生。"""
    wp, _ = _make(empty_graph, mock_llm)
    mock_llm.set_response("extract_work_events", [])
    wp.ingest(IngestInput(content="演义世界观设定：天下三分。", work_id="三国演义"))
    assert _events(empty_graph, "三国演义") == []  # MUST NOT 规则产生作品事件


# === 4.2 叙事时间线 ===


def _seed_timeline_graph(store) -> None:
    for i, (nid, ts) in enumerate([
        ("e200", "200 年"), ("e184", "184 年"), ("e_none", None), ("e189", "189 年"),
    ]):
        meta = {"timestamp": ts} if ts else {}
        store.add_node(Node(
            id=nid, name=f"ev{i}", content=f"发生{i}", node_class=CLASS_EVENT,
            universe="三国演义", extensions={"event_meta": meta},
        ))


def test_narrative_timeline_sorted_by_year_ascending(empty_graph, mock_llm) -> None:
    """时间线按数字年升序；无纪年垫底；查询期组装不落新节点。"""
    _seed_timeline_graph(empty_graph)
    _, qe = _make(empty_graph, mock_llm)
    n_before = len(empty_graph.get_all_nodes())
    tl = qe.narrative_timeline("三国演义")
    assert [n.id for n in tl] == ["e184", "e189", "e200", "e_none"]
    assert len(empty_graph.get_all_nodes()) == n_before  # 不落图
    # limit 从头部（最早）截取
    assert [n.id for n in qe.narrative_timeline("三国演义", limit=2)] == ["e184", "e189"]


def test_narrative_timeline_empty_universe(empty_graph, mock_llm) -> None:
    _, qe = _make(empty_graph, mock_llm)
    assert qe.narrative_timeline("不存在的作品") == []


# === 4.3 每 universe 独立时间轴 ===


def test_per_universe_timeline_no_cross_contamination(empty_graph, mock_llm) -> None:
    """演义"200 年"不进现实时间轴；现实"今天"不进演义时间轴。"""
    _seed_timeline_graph(empty_graph)
    empty_graph.add_node(Node(
        id="e_real", name="今天摄入", content="今天读了演义", node_class=CLASS_EVENT,
        universe=REALITY_UNIVERSE,
        extensions={"event_meta": {"timestamp": "2026-07-14T08:00:00"}},
    ))
    _, qe = _make(empty_graph, mock_llm)
    work_tl = qe.narrative_timeline("三国演义")
    real_tl = qe.narrative_timeline(REALITY_UNIVERSE)
    assert "e_real" not in [n.id for n in work_tl]
    assert [n.id for n in real_tl] == ["e_real"]


# === 4.4 纪年排序口径（非 ISO 容错 + 数字年最小解析） ===


def test_timestamp_sort_value_numeric_year_and_fallback() -> None:
    assert timestamp_sort_value("200 年") == 200.0
    assert timestamp_sort_value("184") == 184.0
    assert timestamp_sort_value("2043年1月") == 2043.0  # 年粒度（同年失序，Phase 1 口径）
    assert timestamp_sort_value("建安五年") == float("-inf")  # 非数字纪年垫底、不抛
    assert timestamp_sort_value("") == float("-inf")
    assert timestamp_sort_value(None) == float("-inf")
    # ISO 路径不受影响
    assert timestamp_sort_value("2026-07-14T08:00:00") > 1e9


def test_event_sort_key_non_iso_no_raise() -> None:
    node = Node(id="x", name="ev", content="…", node_class=CLASS_EVENT,
                universe="w", extensions={"event_meta": {"timestamp": "建安五年"}})
    v, nid = event_sort_key(node)  # 不抛
    assert v == float("-inf") and nid == "x"


# === 4.5 get_related_events universe 过滤 ===


@pytest.fixture()
def endorsed_fact_graph(empty_graph):
    """作品 fact 连两类背书事件：现实摄入（跨 universe）+ 作品叙事（同 universe）。"""
    empty_graph.add_node(Node(id="f", name="fact", content="曹操杀吕伯奢",
                              node_class="事实", universe="三国演义"))
    empty_graph.add_node(Node(
        id="ev_real", name="摄入", content="读演义", node_class=CLASS_EVENT,
        universe=REALITY_UNIVERSE,
        extensions={"event_meta": {"timestamp": "2026-07-14T08:00:00"}},
    ))
    empty_graph.add_node(Node(
        id="ev_work", name="杀吕伯奢", content="……", node_class=CLASS_EVENT,
        universe="三国演义", extensions={"event_meta": {"timestamp": "200 年"}},
    ))
    empty_graph.add_edge("ev_real", "f", type=EDGE_ASSOC)
    empty_graph.add_edge("ev_work", "f", type=EDGE_ASSOC)
    return empty_graph


def test_get_related_events_none_returns_all(endorsed_fact_graph) -> None:
    """universe=None（默认）全返（含跨 universe）——保 mug 查出处语义。"""
    got = {n.id for n in endorsed_fact_graph.get_related_events("f")}
    assert got == {"ev_real", "ev_work"}


def test_get_related_events_universe_filters(endorsed_fact_graph) -> None:
    """传 universe 才过滤：现实只返摄入事件、作品只返叙事事件。"""
    s = endorsed_fact_graph
    assert [n.id for n in s.get_related_events("f", universe=REALITY_UNIVERSE)] == ["ev_real"]
    assert [n.id for n in s.get_related_events("f", universe="三国演义")] == ["ev_work"]


def test_get_related_events_both_stores_consistent(endorsed_fact_graph, tmp_path) -> None:
    """双实现一致：同图 InMemory vs SQLite，同 universe 参数结果一致。"""
    from mcs.stores.sqlite_store import SQLiteStore

    sq = SQLiteStore({"path": str(tmp_path / "g.db")})
    for n in endorsed_fact_graph.get_all_nodes():
        sq.add_node(dataclasses.replace(n))
    for e in endorsed_fact_graph.get_all_edges():
        sq.add_edge(e.source_id, e.target_id, type=e.type)
    for uni in (None, REALITY_UNIVERSE, "三国演义"):
        a = [n.id for n in endorsed_fact_graph.get_related_events("f", universe=uni)]
        b = [n.id for n in sq.get_related_events("f", universe=uni)]
        assert a == b, uni


# === 4.6 WorkEventDraft 语义边界 ===


def test_work_event_draft_distinct_dataclass() -> None:
    """WorkEventDraft 与 EventData / ConceptDraft 并列、不复用（字段与语义不混）。"""
    d = WorkEventDraft(name="e", content="c", narr_timestamp="200 年",
                       participants=["曹操"])
    assert not isinstance(d, EventData)
    assert not isinstance(d, ConceptDraft)
    # ConceptDraft 无 timestamp 语义；EventData 无 participants/narr_timestamp
    assert not hasattr(ConceptDraft(name="x", content="y"), "narr_timestamp")
    assert not hasattr(EventData(name="x", content="y"), "narr_timestamp")
    assert d.participants == ["曹操"]


# === 4.7 转述时间不盖用户时间轴 ===


def test_narrated_time_does_not_pollute_user_timeline(empty_graph, mock_llm) -> None:
    """"今天读了讲三年前故事的书"（带 work_id）：用户时间轴只有"今天读书"摄入事件；
    作品叙述发生走作品事件层，不在现实时间轴出现。"""
    wp, qe = _make(empty_graph, mock_llm)
    mock_llm.set_response("extract_work_events", [
        WorkEventDraft(name="主角出走", content="主角离家出走",
                       narr_timestamp="三年前", participants=[]),
    ])
    wp.ingest(IngestInput(
        content="主角三年前离家出走……", work_id="某小说",
        timestamp="2026-07-14T09:00:00",
    ))
    real_tl = qe.narrative_timeline(REALITY_UNIVERSE)
    work_tl = qe.narrative_timeline("某小说")
    assert len(real_tl) == 1 and real_tl[0].universe == REALITY_UNIVERSE
    assert _ts(real_tl[0]) == "2026-07-14T09:00:00"  # 用户时间轴 = 摄入行为时间
    assert len(work_tl) == 1 and work_tl[0].name == "主角出走"
    assert _ts(work_tl[0]) == "三年前"  # 叙述时间只在作品时间轴
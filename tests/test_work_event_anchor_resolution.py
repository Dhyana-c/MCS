"""work-event-anchor-resolution 测试：叙事时间戳锚点解析（日精度）。

覆盖 tasks T2：
- prompt 防回归：锚点解析例外（ISO 正例）与"保留原文形态 / 不换算"底线并存
- parse 兼容：ISO narr_timestamp 原样透传进 WorkEventDraft
- 端到端可排序：锚点解析产物（ISO 日期）落 event_meta 后可排序、时间线按日期升序
- 行为不变：原文形态（作品纪年 / 相对词）仍原样落图、排序垫底
"""

from __future__ import annotations

from mcs.core.plugin_manager import PluginManager
from mcs.core.query_engine import QueryEngine
from mcs.core.token_budget import TokenBudget
from mcs.core.write_pipeline import WritePipeline
from mcs.entities.decisions import IngestInput, WorkEventDraft
from mcs.entities.graph import CLASS_EVENT
from mcs.prompts.extract_work_events import SYSTEM_PROMPT, parse
from mcs.utils.timestamps import timestamp_sort_value


def _make(store, mock_llm) -> tuple[WritePipeline, QueryEngine]:
    pm = PluginManager()
    pm.register(mock_llm)
    tb = TokenBudget(8000)
    qe = QueryEngine(store=store, llm=mock_llm, plugin_manager=pm, token_budget=tb)
    wp = WritePipeline(
        store=store, llm=mock_llm, query_engine=qe, plugin_manager=pm, token_budget=tb
    )
    return wp, qe


def _work_events(store, universe: str):
    return [e for e in store.get_nodes_by_class(CLASS_EVENT) if e.universe == universe]


def _ts(node) -> str | None:
    return ((node.extensions or {}).get("event_meta") or {}).get("timestamp")


# === prompt 防回归 ===


def test_prompt_contains_anchor_resolution_rule() -> None:
    """锚点解析例外进 prompt：ISO 正例 + 日精度门槛 + 残缺形态禁令。"""
    assert "锚点" in SYSTEM_PROMPT
    assert "2023-05-07" in SYSTEM_PROMPT  # ISO 正例（8 May, 2023 + yesterday）
    assert "具体某天" in SYSTEM_PROMPT  # 日精度门槛（定不到则保留原文）
    assert "2023-05" in SYSTEM_PROMPT  # 残缺形态禁令示例（混尺防护，见 design D2）


def test_prompt_keeps_no_conversion_baseline() -> None:
    """防幻觉底线不动：保留原文形态 / 不换算规则仍在（建安五年类不受影响）。"""
    assert "保留原文形态" in SYSTEM_PROMPT
    assert "不换算" in SYSTEM_PROMPT
    assert "建安五年" in SYSTEM_PROMPT


# === parse 兼容 ===


def test_parse_passes_iso_timestamp_through() -> None:
    raw = (
        '[{"name": "Sarah 去互助会", "content": "Sarah attended a support group.", '
        '"narr_timestamp": "2023-05-07", "participants": ["Sarah"]}]'
    )
    drafts = parse(raw)
    assert len(drafts) == 1
    assert drafts[0].narr_timestamp == "2023-05-07"  # 原样透传，不被改写


# === 端到端：ISO 产物可排序、时间线按日期升序 ===


def test_anchor_resolved_iso_sortable_end_to_end(empty_graph, mock_llm) -> None:
    mock_llm.set_response("extract_work_events", [
        WorkEventDraft(name="去互助会", content="Sarah attended a support group.",
                       narr_timestamp="2023-05-07", participants=[]),
        WorkEventDraft(name="领养讲座", content="Sarah attended an adoption seminar.",
                       narr_timestamp="2023-05-06", participants=[]),
    ])
    wp, qe = _make(empty_graph, mock_llm)
    wp.ingest(IngestInput(
        content="[1:56 pm on 8 May, 2023] Sarah: I went to a support group yesterday...",
        work_id="conv-26", timestamp="2023-05-08T13:56:00",
    ))
    evs = _work_events(empty_graph, "conv-26")
    assert {_ts(e) for e in evs} == {"2023-05-07", "2023-05-06"}
    assert all(timestamp_sort_value(_ts(e)) != float("-inf") for e in evs)
    # 叙事时间线按 ISO 日期升序
    tl = qe.narrative_timeline("conv-26")
    assert [_ts(e) for e in tl] == ["2023-05-06", "2023-05-07"]


def test_unresolved_original_form_bottoms_timeline(empty_graph, mock_llm) -> None:
    """定不到具体某天的原文形态（last week）与作品纪年：原样落图、时间线垫底。"""
    mock_llm.set_response("extract_work_events", [
        WorkEventDraft(name="慈善跑", content="Melanie ran a charity race.",
                       narr_timestamp="last week", participants=[]),
        WorkEventDraft(name="去互助会", content="Sarah attended a support group.",
                       narr_timestamp="2023-05-07", participants=[]),
    ])
    wp, qe = _make(empty_graph, mock_llm)
    wp.ingest(IngestInput(
        content="[1:56 pm on 8 May, 2023] Sarah: ...", work_id="conv-26",
        timestamp="2023-05-08T13:56:00",
    ))
    tl = qe.narrative_timeline("conv-26")
    # ISO 在前、不可排原文垫底（原样保留、不被改写不丢弃）
    assert [_ts(e) for e in tl] == ["2023-05-07", "last week"]
    assert timestamp_sort_value("last week") == float("-inf")


def test_work_calendar_unaffected(empty_graph, mock_llm) -> None:
    """无锚点作品纪年行为不变：建安五年原样落图（不换算），数字年仍可排。"""
    mock_llm.set_response("extract_work_events", [
        WorkEventDraft(name="曹操杀吕伯奢", content="曹操疑心误杀吕伯奢全家",
                       narr_timestamp="建安五年", participants=[]),
        WorkEventDraft(name="黄巾起义", content="黄巾军起事",
                       narr_timestamp="184 年", participants=[]),
    ])
    wp, qe = _make(empty_graph, mock_llm)
    wp.ingest(IngestInput(content="建安五年，曹操……", work_id="三国演义"))
    tl = qe.narrative_timeline("三国演义")
    assert [_ts(e) for e in tl] == ["184 年", "建安五年"]  # 数字年可排、混合纪年垫底

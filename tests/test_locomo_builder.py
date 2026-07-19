# -*- coding: utf-8 -*-
"""bench.locomo 对话式 ingest 建图测试（不调真实 LLM）。

覆盖：会话拼接格式、ingest 调用契约（``work_id`` / ``timestamp`` / ``chunk_id``）、
resume（db 已存在则跳过）、``work_id``→③b 门控（谈话中的事件落对话 universe、当下事件
落 ``__reality__``）。③b 抽取质量属真实 LLM 行为，由 conv-26 试点验收，不在此单测。
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from mcs.entities.decisions import IngestInput, WorkEventDraft

from bench.locomo.builder import (
    build_all_graphs,
    build_locomo_graph,
    format_session_text,
    ingest_doc_sessions,
    selfcheck_graph,
)
from bench.locomo.data import LoCoMoDoc, LoCoMoSession, LoCoMoTurn


def _session(session_id: int, turns: list[tuple[str, str, str | None]], ts_iso: str = "2023-05-08T13:56:00") -> LoCoMoSession:
    return LoCoMoSession(
        session_id=session_id,
        datetime_raw="1:56 pm on 8 May, 2023",
        timestamp_iso=ts_iso,
        turns=[
            LoCoMoTurn(speaker=sp, text=txt, dia_id=f"D{session_id}:{i+1}",
                       session=session_id, caption=cap)
            for i, (sp, txt, cap) in enumerate(turns)
        ],
    )


def _doc(sample_id: str = "conv-26") -> LoCoMoDoc:
    return LoCoMoDoc(
        sample_id=sample_id, speaker_a="Sarah", speaker_b="Jessica",
        sessions=[
            _session(1, [("Sarah", "Hey Jess!", None), ("Jessica", "[shared image]", "a bowl")]),
            _session(2, [("Sarah", "I went to a group yesterday.", None)]),
        ],
    )


# ---------------------------------------------------------------------------
# format_session_text（纯函数）
# ---------------------------------------------------------------------------


class TestFormatSessionText:
    def test_prepends_time_and_speaker(self):
        s = _session(1, [("Sarah", "Hey Jess!", None)])
        text = format_session_text(s)
        assert text.startswith("[1:56 pm on 8 May, 2023] Sarah: Hey Jess!")

    def test_caption_appended_on_image_turn(self):
        s = _session(1, [("Jessica", "look", "a photo of a bowl")])
        text = format_session_text(s)
        assert text.endswith(" [shared image: a photo of a bowl]")

    def test_no_caption_suffix_on_plain_turn(self):
        s = _session(1, [("Sarah", "plain text", None)])
        assert "[shared image:" not in format_session_text(s)

    def test_multi_turn_joined_by_newline(self):
        s = _session(1, [("Sarah", "a", None), ("Jessica", "b", None)])
        text = format_session_text(s)
        assert text.count("\n") == 1
        assert text.split("\n")[0].startswith("[")

    def test_all_turns_share_session_time(self):
        s = _session(1, [("Sarah", "a", None), ("Jessica", "b", None)])
        text = format_session_text(s)
        for line in text.split("\n"):
            assert line.startswith("[1:56 pm on 8 May, 2023] ")


# ---------------------------------------------------------------------------
# ingest_doc_sessions（MagicMock mcs，验证调用契约）
# ---------------------------------------------------------------------------


class TestIngestDocSessions:
    def test_calls_ingest_once_per_session(self):
        mcs = MagicMock()
        mcs.ingest.return_value = MagicMock(work_event_nodes=[])
        doc = _doc()
        ingest_doc_sessions(mcs, doc)
        assert mcs.ingest.call_count == len(doc.sessions)

    def test_ingest_input_carries_work_id_and_timestamp(self):
        mcs = MagicMock()
        mcs.ingest.return_value = MagicMock(work_event_nodes=[])
        doc = _doc()
        ingest_doc_sessions(mcs, doc)
        first_call = mcs.ingest.call_args_list[0]
        args, kwargs = first_call
        inp = args[0]
        assert isinstance(inp, IngestInput)
        assert inp.work_id == doc.sample_id  # 启用 ③b
        assert inp.timestamp == "2023-05-08T13:56:00"  # 会话时间回填
        assert "[1:56 pm on 8 May, 2023] Sarah:" in inp.content  # 拼接文本

    def test_source_tracking_kwargs(self):
        mcs = MagicMock()
        mcs.ingest.return_value = MagicMock(work_event_nodes=[])
        doc = _doc()
        ingest_doc_sessions(mcs, doc)
        _, kwargs = mcs.ingest.call_args_list[0]
        assert kwargs["doc_id"] == doc.sample_id
        assert kwargs["chunk_id"] == "session_1"
        assert kwargs["section_title"] == doc.sample_id
        # 第二个会话 chunk_id 递增
        _, kwargs2 = mcs.ingest.call_args_list[1]
        assert kwargs2["chunk_id"] == "session_2"

    def test_returns_narrative_event_counts(self):
        mcs = MagicMock()
        # 每会话抽 2、0 个叙事事件
        mcs.ingest.side_effect = [MagicMock(work_event_nodes=[1, 2]), MagicMock(work_event_nodes=[])]
        counts = ingest_doc_sessions(mcs, _doc())
        assert counts == [2, 0]

    def test_save_full_called_once(self):
        mcs = MagicMock()
        mcs.ingest.return_value = MagicMock(work_event_nodes=[])
        ingest_doc_sessions(mcs, _doc())
        mcs.store.save_full.assert_called_once()


# ---------------------------------------------------------------------------
# build_locomo_graph resume
# ---------------------------------------------------------------------------


class TestBuildLocomoGraphResume:
    def test_skips_existing_db(self, tmp_path):
        doc = _doc()
        db = tmp_path / f"locomo_{doc.sample_id}.db"
        db.write_bytes(b"")  # 模拟已建
        with patch("bench.locomo.builder._make_mcs") as mk:
            stats = build_locomo_graph(doc, db_dir=tmp_path)
        assert stats["skipped"] is True
        mk.assert_not_called()  # 跳过即不构造 MCS

    def test_force_rebuilds(self, tmp_path):
        doc = _doc()
        db = tmp_path / f"locomo_{doc.sample_id}.db"
        db.write_bytes(b"")
        with patch("bench.locomo.builder._make_mcs") as mk:
            fake = MagicMock()
            fake.ingest.return_value = MagicMock(work_event_nodes=[])
            mk.return_value = fake
            stats = build_locomo_graph(doc, db_dir=tmp_path, force=True)
        assert stats["skipped"] is False
        mk.assert_called_once()

    def test_builds_when_absent(self, tmp_path):
        doc = _doc()
        with patch("bench.locomo.builder._make_mcs") as mk:
            fake = MagicMock()
            fake.ingest.return_value = MagicMock(work_event_nodes=[MagicMock()])
            mk.return_value = fake
            stats = build_locomo_graph(doc, db_dir=tmp_path)
        assert stats["skipped"] is False
        assert stats["sessions"] == 2
        assert stats["narrative_events_total"] == 2
        assert (tmp_path / f"locomo_{doc.sample_id}.db").exists() is False  # mock 不写真 db


def test_build_all_graphs_pilot_first(tmp_path):
    docs = [_doc("conv-30"), _doc("conv-26"), _doc("conv-41")]
    with patch("bench.locomo.builder._make_mcs") as mk:
        fake = MagicMock()
        fake.ingest.return_value = MagicMock(work_event_nodes=[])
        mk.return_value = fake
        stats = build_all_graphs(docs, db_dir=tmp_path, sample_ids={"conv-30", "conv-26"})
    # conv-26 试点排最前
    assert [s["sample_id"] for s in stats] == ["conv-26", "conv-30"]


# ---------------------------------------------------------------------------
# work_id → ③b 门控（mcs_with_mock_llm，验证双轨事件不变量）
# ---------------------------------------------------------------------------


class TestWorkEventGating:
    def test_work_id_triggers_extract_work_events(self, mcs_with_mock_llm, mock_llm):
        mock_llm.call_log.clear()
        mcs_with_mock_llm.ingest(
            IngestInput(content="Sarah went to a support group yesterday.",
                        work_id="conv-26", timestamp="2023-05-08T13:56:00")
        )
        purposes = [c["purpose"] for c in mock_llm.call_log]
        assert "extract_work_events" in purposes  # work_id 非空 → ③b 触发

    def test_no_work_id_skips_extract_work_events(self, mcs_with_mock_llm, mock_llm):
        mock_llm.call_log.clear()
        mcs_with_mock_llm.ingest("Sarah went to a support group yesterday.")  # 无 work_id
        purposes = [c["purpose"] for c in mock_llm.call_log]
        assert "extract_work_events" not in purposes  # 无 work_id → ③b 不触发

    def test_dual_track_universes(self, mcs_with_mock_llm, mock_llm):
        # 让 ③b 产 1 条叙事事件
        mock_llm.set_response(
            "extract_work_events",
            [WorkEventDraft(name="Sarah 去互助会", content="Sarah attended a support group.",
                            narr_timestamp="2023-05-07", participants=["Sarah"])],
        )
        ctx = mcs_with_mock_llm.ingest(
            IngestInput(content="Sarah went to a support group yesterday.",
                        work_id="conv-26", timestamp="2023-05-08T13:56:00")
        )
        # 当下事件（摄入行为）落 __reality__
        assert ctx.event_node.universe == "__reality__"
        # 谈话中的事件（③b）落对话 universe
        assert len(ctx.work_event_nodes) >= 1
        for ev in ctx.work_event_nodes:
            assert ev.universe == "conv-26"
            assert ev.node_class == "事件"


class TestSelfcheckGraph:
    def test_reports_narrative_and_ingest_counts(self, mcs_with_mock_llm, mock_llm):
        # 2 条叙事事件：一条 ISO（可排序）、一条 "yesterday"（不可排序）
        mock_llm.set_response("extract_work_events", [
            WorkEventDraft(name="e1", content="c1", narr_timestamp="2023-05-07", participants=[]),
            WorkEventDraft(name="e2", content="c2", narr_timestamp="yesterday", participants=[]),
        ])
        mcs_with_mock_llm.ingest(IngestInput(
            content="Sarah went to a group yesterday.",
            work_id="conv-26", timestamp="2023-05-08T13:56:00"))
        sc = selfcheck_graph(mcs_with_mock_llm, "conv-26")
        assert sc["narrative_events"] == 2
        assert sc["ingest_events"] == 1  # 当下事件落 __reality__
        assert sc["sortable_ratio"] == 0.5  # 仅 ISO 那条可排序
        assert set(sc["timestamp_samples"]) == {"2023-05-07", "yesterday"}  # 形态抽样供人工核对
        assert sc["universe_ok"] is True

    def test_empty_graph_safe(self, mcs_with_mock_llm):
        sc = selfcheck_graph(mcs_with_mock_llm, "conv-empty")
        assert sc["narrative_events"] == 0
        assert sc["sortable_ratio"] == 0.0
        assert sc["universe_ok"] is True

# -*- coding: utf-8 -*-
"""bench.locomo 评测脚本测试（不调真实 LLM；agent / judge / mcs.query 均 mock）。

覆盖：system prompt 构造、对话选择（conv-26 优先）、resume、QA 轨记录 schema、检索轨记录
schema、报告口径分离（主表 judge / 副表 F1·temporal·检索）。真实 agent.chat / mcs.query /
③b 抽取质量由 conv-26 试点验收，不在此单测。
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from bench.locomo import scripts as scripts_pkg  # noqa: F401  保证包可 import
from bench.locomo.data import LoCoMoDoc, LoCoMoQA, LoCoMoSession, LoCoMoTurn
from bench.locomo.scripts import agent_eval as ae
from bench.locomo.scripts.analyze import write_report


def _doc(sample_id="conv-26", n_qa=3) -> LoCoMoDoc:
    qa = [
        LoCoMoQA(qid=f"{sample_id}-q{i}", question=f"Q{i}?", category=(i % 5) + 1,
                 answer=f"ans{i}" if (i % 5) + 1 != 5 else None,
                 adversarial_answer="trap" if (i % 5) + 1 == 5 else None,
                 evidence=[f"D{i+1}:1"] if i < 2 else [])
        for i in range(n_qa)
    ]
    sess = LoCoMoSession(session_id=1, datetime_raw="1:56 pm on 8 May, 2023",
                         timestamp_iso="2023-05-08T13:56:00",
                         turns=[LoCoMoTurn("Sarah", "hi", "D1:1", 1)])
    return LoCoMoDoc(sample_id=sample_id, speaker_a="Sarah", speaker_b="Jessica",
                     sessions=[sess], qa_list=qa)


# ---------------------------------------------------------------------------
# prompt / 选对话 / resume 纯逻辑
# ---------------------------------------------------------------------------


def test_build_query_system_prompt():
    d = _doc()
    p = ae.build_query_system_prompt(d)
    assert "Sarah" in p and "Jessica" in p
    assert "universe=conv-26" in p  # timeline universe 提示
    assert "peer-to-peer" in p
    assert "{doc.sample_id}" not in p  # 防 f-string 前缀丢失回归
    assert "recall" not in p  # recall 不在 QUERY_TOOLS，prompt 不应提及


class TestSelectConversations:
    def test_pilot_first(self):
        docs = [_doc("conv-30"), _doc("conv-26"), _doc("conv-41")]
        out = ae.select_conversations(docs)
        assert [d.sample_id for d in out] == ["conv-26", "conv-30", "conv-41"]

    def test_max_conversations_limit(self):
        docs = [_doc("conv-26"), _doc("conv-30"), _doc("conv-41")]
        out = ae.select_conversations(docs, max_conversations=2)
        assert [d.sample_id for d in out] == ["conv-26", "conv-30"]

    def test_sample_ids_filter(self):
        docs = [_doc("conv-26"), _doc("conv-30"), _doc("conv-41")]
        out = ae.select_conversations(docs, sample_ids={"conv-41"})
        assert [d.sample_id for d in out] == ["conv-41"]


def test_load_done_resume(tmp_path):
    p = tmp_path / "qa_results_conv-26.jsonl"
    p.write_text(
        json.dumps({"qid": "q1", "judge_correct": True}) + "\n"
        + "bad line\n"
        + json.dumps({"qid": "q2", "judge_correct": False}) + "\n",
        encoding="utf-8",
    )
    done = ae._load_done(p)
    assert set(done) == {"q1", "q2"}


# ---------------------------------------------------------------------------
# QA 轨（mock MemoryAgent + judge_correct + _make_mcs）
# ---------------------------------------------------------------------------


class TestRunAgentEval:
    def test_writes_records_and_resumes(self, tmp_path):
        doc = _doc(n_qa=3)
        db = tmp_path / f"locomo_{doc.sample_id}.db"
        db.write_bytes(b"")
        out = tmp_path / "out"

        agent = MagicMock()
        agent.chat.side_effect = ["reply0", "reply1", "reply2"]
        with patch.object(ae, "MemoryAgent", return_value=agent), \
                patch.object(ae, "judge_correct", return_value=True), \
                patch.object(ae, "_make_mcs", return_value=MagicMock()):
            stats = ae.run_agent_eval(
                doc, db, out, llm_call=lambda m, t: {},
                token_budget=100, max_turns=2,
            )
        assert stats["evaluated"] == 3
        recs = [json.loads(l) for l in (out / f"qa_results_{doc.sample_id}.jsonl").read_text(encoding="utf-8").splitlines()]
        assert len(recs) == 3
        r0 = recs[0]
        # 记录 schema
        for key in ("qid", "sample_id", "category", "question", "reply",
                    "judge_correct", "f1", "n_llm_agent", "tokens_agent", "wall_s"):
            assert key in r0
        assert r0["judge_correct"] is True
        assert r0["reply"] == "reply0"

        # resume：再跑无新增
        with patch.object(ae, "MemoryAgent", return_value=MagicMock()), \
                patch.object(ae, "judge_correct"), \
                patch.object(ae, "_make_mcs", return_value=MagicMock()):
            stats2 = ae.run_agent_eval(
                doc, db, out, llm_call=lambda m, t: {},
                token_budget=100, max_turns=2,
            )
        assert stats2["skipped_all"] is True

    def test_workers_parallel_writes_all(self, tmp_path):
        """workers>1：全部题并发评完、记录不重不漏（写入加锁）。"""
        doc = _doc(n_qa=6)
        db = tmp_path / f"locomo_{doc.sample_id}.db"
        db.write_bytes(b"")
        out = tmp_path / "out"
        agent = MagicMock()
        agent.chat.side_effect = lambda q: f"reply-{q}"  # 无共享状态，线程安全
        with patch.object(ae, "MemoryAgent", return_value=agent), \
                patch.object(ae, "judge_correct", return_value=True), \
                patch.object(ae, "_make_mcs", return_value=MagicMock()):
            stats = ae.run_agent_eval(
                doc, db, out, llm_call=lambda m, t: {},
                token_budget=100, max_turns=2, workers=3,
            )
        assert stats["evaluated"] == 6
        recs = [json.loads(l) for l in (out / f"qa_results_{doc.sample_id}.jsonl")
                .read_text(encoding="utf-8").splitlines()]
        assert len(recs) == 6
        assert {r["qid"] for r in recs} == {q.qid for q in doc.qa_list}  # 不重不漏

    def test_workers_parallel_fail_limit_stops(self, tmp_path):
        """并发熔断：全局失败计数达 fail_limit 取消剩余（可续跑）。"""
        doc = _doc(n_qa=6)
        db = tmp_path / f"locomo_{doc.sample_id}.db"
        db.write_bytes(b"")
        out = tmp_path / "out"
        agent = MagicMock()
        agent.chat.side_effect = RuntimeError("端点挂了")
        with patch.object(ae, "MemoryAgent", return_value=agent), \
                patch.object(ae, "judge_correct", return_value=True), \
                patch.object(ae, "_make_mcs", return_value=MagicMock()):
            stats = ae.run_agent_eval(
                doc, db, out, llm_call=lambda m, t: {},
                token_budget=100, max_turns=2, workers=2, fail_limit=2,
            )
        assert stats["evaluated"] == 0  # 无成功记录；熔断后剩余被取消

    def test_max_questions_limits_new_evals(self, tmp_path):
        doc = _doc(n_qa=3)
        db = tmp_path / f"locomo_{doc.sample_id}.db"
        db.write_bytes(b"")
        out = tmp_path / "out"
        agent = MagicMock()
        agent.chat.side_effect = ["reply0", "reply1", "reply2"]
        with patch.object(ae, "MemoryAgent", return_value=agent), \
                patch.object(ae, "judge_correct", return_value=True), \
                patch.object(ae, "_make_mcs", return_value=MagicMock()):
            stats = ae.run_agent_eval(
                doc, db, out, llm_call=lambda m, t: {},
                token_budget=100, max_turns=2, max_questions=2,
            )
        assert stats["evaluated"] == 2  # 限量 2 题
        recs = (out / f"qa_results_{doc.sample_id}.jsonl").read_text(encoding="utf-8").splitlines()
        assert len(recs) == 2

    def test_temporal_accept_only_cat2(self, tmp_path):
        doc = _doc(n_qa=2)
        # 第 0 题 cat-2（temporal），第 1 题显式 cat-4（非 temporal）
        doc.qa_list[0].category = 2
        doc.qa_list[0].answer = "7 May 2023"
        doc.qa_list[1].category = 4
        db = tmp_path / f"locomo_{doc.sample_id}.db"
        db.write_bytes(b"")
        out = tmp_path / "out"
        agent = MagicMock()
        agent.chat.side_effect = ["7 May 2023", "reply1"]
        with patch.object(ae, "MemoryAgent", return_value=agent), \
                patch.object(ae, "judge_correct", return_value=True), \
                patch.object(ae, "_make_mcs", return_value=MagicMock()):
            ae.run_agent_eval(doc, db, out, llm_call=lambda m, t: {}, token_budget=100, max_turns=2)
        recs = [json.loads(l) for l in (out / f"qa_results_{doc.sample_id}.jsonl").read_text(encoding="utf-8").splitlines()]
        assert "temporal_accept" in recs[0]  # cat-2 带
        assert "temporal_accept" not in recs[1]  # 非 temporal 不带


# ---------------------------------------------------------------------------
# 检索轨（mock mcs.query）
# ---------------------------------------------------------------------------


class TestRunRetrievalEval:
    def test_writes_ranked_sessions(self, tmp_path):
        doc = _doc(n_qa=3)  # 前 2 题有 evidence
        db = tmp_path / f"locomo_{doc.sample_id}.db"
        db.write_bytes(b"")
        out = tmp_path / "out"

        # mock 节点带 source_tracking chunk_id
        def mk_node(chunk):
            return MagicMock(extensions={"source_tracking": {"sources": [MagicMock(chunk_id=chunk)]}})
        sub = MagicMock(nodes=[mk_node("session_1"), mk_node("session_2")])
        mcs = MagicMock()
        mcs.query.return_value = sub
        with patch.object(ae, "_make_mcs", return_value=mcs):
            stats = ae.run_retrieval_eval(doc, db, out, token_budget=100)
        assert stats["evaluated"] == 2  # 仅 evidence 题
        recs = [json.loads(l) for l in (out / f"retrieval_results_{doc.sample_id}.jsonl").read_text(encoding="utf-8").splitlines()]
        assert recs[0]["ranked_sessions"] == [1, 2]
        assert recs[0]["gold_sessions"] == [1]  # evidence D1:1


# ---------------------------------------------------------------------------
# 报告（口径分离）
# ---------------------------------------------------------------------------


class TestWriteReport:
    def test_separates_judge_from_f1_and_has_baseline(self, tmp_path):
        out = tmp_path / "out"
        out.mkdir()
        qa = [
            {"qid": "q1", "sample_id": "conv-26", "category": 1, "judge_correct": True, "f1": 0.8, "reply": "a"},
            {"qid": "q2", "sample_id": "conv-26", "category": 5, "judge_correct": False, "f1": 0.0, "reply": "trap"},
        ]
        (out / "qa_results_conv-26.jsonl").write_text(
            "\n".join(json.dumps(r, ensure_ascii=False) for r in qa) + "\n", encoding="utf-8")
        agg = write_report(out)
        report = (out / "REPORT.md").read_text(encoding="utf-8")
        # 主表与副表都存在
        assert "主表：LLM-judge" in report
        assert "副表：F1" in report
        # 基线对比表（LLM-judge 口径，逐行注明来源）
        assert "Mem0" in report and "92.5%" in report
        assert "Zep" in report and "94.7%" in report
        # Human（F1 口径）不混入 LLM-judge 基线对比表主体，出现在 F1 副表
        assert "0.879" in report
        # excl-adversarial（对齐 Mem0）被计算
        assert "排除 adversarial" in report
        assert (out / "metrics.json").exists()
        # 结构上 judge 与 f1 分离
        assert "judge" in agg["qa"] and "f1" in agg["qa"]

    def test_no_results_safe(self, tmp_path):
        out = tmp_path / "empty"
        out.mkdir()
        agg = write_report(out)
        assert agg == {}

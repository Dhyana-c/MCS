# -*- coding: utf-8 -*-
"""bench.locomo 评测指标测试（纯函数，无 LLM；judge 单测 patch ``_call_judge_llm``）。"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from bench.locomo import metrics as M
from bench.locomo.metrics import (
    _parse_verdict,
    aggregate_locomo_metrics,
    aggregate_qa,
    aggregate_retrieval,
    all_evidence_hit,
    any_evidence_hit,
    chunk_id_to_session,
    evidence_to_sessions,
    f1_token_level,
    judge_correct,
    retrieved_sessions,
    session_recall_at_k,
    temporal_offset_accept,
)


# ---------------------------------------------------------------------------
# 检索轨 session 级 Recall@k
# ---------------------------------------------------------------------------


class TestRetrievalPure:
    def test_chunk_id_to_session(self):
        assert chunk_id_to_session("session_3") == 3
        assert chunk_id_to_session("session_12") == 12
        assert chunk_id_to_session("session_X") is None
        assert chunk_id_to_session("3") is None

    def test_evidence_to_sessions(self):
        assert evidence_to_sessions(["D1:3", "D2:8", "D1:9"]) == {1, 2}
        assert evidence_to_sessions([]) == set()

    def test_spec_hit_scenario(self):
        # spec scenario：k=5，ranked 前 5 = [3,1,7,4,9]，gold={1,2}
        ranked = [3, 1, 7, 4, 9]
        gold = {1, 2}
        assert any_evidence_hit(ranked, gold, 5) is True
        assert all_evidence_hit(ranked, gold, 5) is False

    def test_all_hit_when_all_in_topk(self):
        ranked = [1, 2, 3]
        assert all_evidence_hit(ranked, {1, 2}, 3) is True

    def test_recall_fraction(self):
        assert session_recall_at_k([1, 2, 3], {1, 2}, 3) == 1.0
        assert session_recall_at_k([3, 1, 7], {1, 2}, 3) == 0.5
        assert session_recall_at_k([3, 4], {1, 2}, 2) == 0.0

    def test_empty_gold_guards(self):
        assert session_recall_at_k([1], set(), 2) == 0.0
        assert any_evidence_hit([1], set(), 2) is False
        assert all_evidence_hit([1], set(), 2) is False

    def test_retrieved_sessions_reads_chunk_id(self):
        # 节点 extensions.source_tracking.sources[].chunk_id（session 级，doc_id 恒定不区分）
        def node(chunks):
            src = [MagicMock(chunk_id=c) for c in chunks]
            return MagicMock(extensions={"source_tracking": {"sources": src}})

        nodes = [node(["session_3", "session_1"]), node(["session_1", "session_7"])]
        # 按 rank 去重保序
        assert retrieved_sessions(nodes) == [3, 1, 7]

    def test_retrieved_sessions_handles_dict_source(self):
        # 旧库 Source 可能反序列化成 dict
        node = MagicMock(extensions={"source_tracking": {"sources": [{"chunk_id": "session_2"}]}})
        assert retrieved_sessions([node]) == [2]


# ---------------------------------------------------------------------------
# F1 token-level
# ---------------------------------------------------------------------------


class TestF1:
    def test_identical(self):
        assert f1_token_level("Alice adopted a cat", "Alice adopted a cat") == 1.0

    def test_stemming_and_articles(self):
        # cats -> cat (stem), a 去除（冠词）→ 仍满分
        assert f1_token_level("Alice adopted cats", "Alice adopted a cat") == 1.0

    def test_partial_overlap(self):
        score = f1_token_level("Alice adopted a cat named Luna", "Alice adopted a dog")
        assert 0.0 < score < 1.0

    def test_no_overlap(self):
        assert f1_token_level("cat", "dog") == 0.0

    def test_empty(self):
        assert f1_token_level("", "anything") == 0.0
        assert f1_token_level("anything", "") == 0.0
        assert f1_token_level(None, None) == 0.0

    def test_punctuation_normalized(self):
        assert f1_token_level("Luna, the cat!", "luna the cat") == 1.0


# ---------------------------------------------------------------------------
# temporal 副指标
# ---------------------------------------------------------------------------


class TestTemporalOffset:
    def test_same_year(self):
        assert temporal_offset_accept("7 May 2023", "7 May 2023") is True
        assert temporal_offset_accept("March 2023", "2023") is True

    def test_off_by_one(self):
        assert temporal_offset_accept("2021", "2020") is True
        assert temporal_offset_accept("2024", "2023") is True

    def test_too_far(self):
        assert temporal_offset_accept("2025", "2020") is False

    def test_no_year(self):
        assert temporal_offset_accept("yesterday", "7 May 2023") is False
        assert temporal_offset_accept("7 May 2023", None) is False


# ---------------------------------------------------------------------------
# judge（patch _call_judge_llm）
# ---------------------------------------------------------------------------


class TestJudge:
    def test_returns_bool(self, monkeypatch):
        monkeypatch.setattr(M, "_call_judge_llm",
                            lambda *a, **k: {"correct": True, "reason": "ok"})
        assert judge_correct("q", "reply", 4, gold_answer="ans") is True

    def test_adversarial_path(self, monkeypatch):
        # adversarial 弃答判定走 judge（不用关键词匹配）——仅验证 plumbing
        monkeypatch.setattr(M, "_call_judge_llm",
                            lambda *a, **k: {"correct": False, "reason": "答出陷阱"})
        assert judge_correct("q", "self-care is important", 5,
                             adversarial_answer="self-care is important") is False


class TestParseVerdict:
    def test_dict_with_content(self):
        raw = {"content": '{"correct": true, "reason": "yes"}'}
        assert _parse_verdict(raw) == {"correct": True, "reason": "yes"}

    def test_plain_json_string(self):
        assert _parse_verdict('{"correct": false, "reason": "no"}')["correct"] is False

    def test_json_embedded_in_text(self):
        raw = "Some preamble {\"correct\": true, \"reason\": \"x\"} trailing"
        assert _parse_verdict(raw)["correct"] is True

    def test_malformed(self):
        v = _parse_verdict("no json here")
        assert v["correct"] is False

    def test_non_text(self):
        assert _parse_verdict(None)["correct"] is False


# ---------------------------------------------------------------------------
# 聚合（口径分离）
# ---------------------------------------------------------------------------


def _qa(cat, judge_correct, f1=0.0, **extra):
    return {"category": cat, "judge_correct": judge_correct, "f1": f1, **extra}


class TestAggregateQA:
    def test_judge_main_table_by_category(self):
        results = [
            _qa(1, True, 0.8), _qa(1, False, 0.2),
            _qa(5, True, 0.0),
        ]
        agg = aggregate_qa(results)
        # 主表 judge
        assert agg["judge"]["cat_1_multi-hop"]["n"] == 2
        assert agg["judge"]["cat_1_multi-hop"]["accuracy"] == 0.5
        assert agg["judge"]["cat_5_adversarial"]["accuracy"] == 1.0
        assert agg["judge"]["overall"]["n"] == 3

    def test_f1_separate_from_main(self):
        results = [_qa(1, True, 0.9), _qa(2, False, 0.1)]
        agg = aggregate_qa(results)
        # F1 在副表，不混入 judge 主表
        assert "mean" in agg["f1"]["overall"]
        assert "accuracy" in agg["judge"]["overall"]
        assert agg["f1"]["overall"]["mean"] == pytest.approx(0.5)

    def test_temporal_offset_only_cat2(self):
        results = [
            _qa(2, True, 0.5, temporal_accept=True),
            _qa(2, False, 0.0, temporal_accept=False),
            _qa(1, True, 1.0),  # 非 temporal，无 temporal_accept
        ]
        agg = aggregate_qa(results)
        assert agg["temporal_offset"]["n"] == 2
        assert agg["temporal_offset"]["accept_rate"] == 0.5


class TestAggregateRetrieval:
    def test_recall_and_hits(self):
        results = [
            {"gold_sessions": [1, 2], "ranked_sessions": [1, 3, 2, 4]},
            {"gold_sessions": [5], "ranked_sessions": [6, 7, 8]},  # miss
        ]
        agg = aggregate_retrieval(results, k_values=(3,))
        assert agg["n"] == 2
        assert agg["any_hit@3"] == 0.5  # 第一题命中
        assert agg["all_hit@3"] == 0.5  # 第一题 top3 含 {1,2}
        assert agg["recall@3"] == pytest.approx((1.0 + 0.0) / 2)

    def test_skips_empty_gold(self):
        results = [{"gold_sessions": [], "ranked_sessions": [1]}]
        agg = aggregate_retrieval(results, k_values=(5,))
        # 无 gold 不计入分母
        assert agg["recall@5"] == 0.0


def test_aggregate_locomo_metrics_separation():
    qa = [_qa(4, True, 0.7)]
    ret = [{"gold_sessions": [1], "ranked_sessions": [1]}]
    agg = aggregate_locomo_metrics(qa, ret, k_values=(5,))
    assert "qa" in agg and "retrieval" in agg
    assert "judge" in agg["qa"] and "f1" in agg["qa"]
    assert agg["qa"]["judge"]["overall"]["accuracy"] == 1.0
    assert agg["retrieval"]["any_hit@5"] == 1.0

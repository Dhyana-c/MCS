# -*- coding: utf-8 -*-
"""bench.locomo 数据装载与三源合成测试（纯逻辑，不调真实 LLM）。

覆盖：时间戳解析、换名词边界、dia_id 映射、caption 按 dia_id 移植、evidence 按换名
映射移植、conv-26 残桩丢弃、qid 唯一性、类别分布漂移报错。真实全量数据集测试用
``skipif`` 门控（数据未生成则跳过）。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from bench.locomo.data import (
    CAPTION_VARIANT_FIELD,
    EXPECTED_CAPTION_COUNT,
    EXPECTED_CATEGORY_COUNTS,
    LoCoMoDataLoader,
    LoCoMoQA,
    apply_rename,
    build_rename_map,
    dia_id_to_session,
    filter_by_category,
    make_qid,
    parse_timestamp,
    strip_audit_tags,
)


# ---------------------------------------------------------------------------
# 纯函数
# ---------------------------------------------------------------------------


class TestParseTimestamp:
    def test_pm_afternoon(self):
        from datetime import datetime
        assert parse_timestamp("1:56 pm on 8 May, 2023") == datetime(2023, 5, 8, 13, 56)

    def test_am_morning(self):
        from datetime import datetime
        assert parse_timestamp("10:37 am on 27 June, 2023") == datetime(2023, 6, 27, 10, 37)

    def test_midnight_noon(self):
        from datetime import datetime
        assert parse_timestamp("12:09 am on 13 September, 2023") == datetime(2023, 9, 13, 0, 9)
        assert parse_timestamp("12:30 pm on 1 January, 2024") == datetime(2024, 1, 1, 12, 30)

    def test_case_insensitive_ampm(self):
        from datetime import datetime
        assert parse_timestamp("1:56 PM on 8 May, 2023") == datetime(2023, 5, 8, 13, 56)

    def test_iso_format_output(self):
        # IngestInput.timestamp 用的就是 .isoformat()
        assert parse_timestamp("1:56 pm on 8 May, 2023").isoformat() == "2023-05-08T13:56:00"

    def test_invalid_raises(self):
        for bad in ["", "not a time", "1:56 on 8 May 2023", "13:56 pm on 8 May, 2023 and junk"]:
            with pytest.raises(ValueError):
                parse_timestamp(bad)

    def test_unknown_month_raises(self):
        with pytest.raises(ValueError):
            parse_timestamp("1:56 pm on 8 Smarch, 2023")


class TestDiaIdToSession:
    def test_valid(self):
        assert dia_id_to_session("D1:3") == 1
        assert dia_id_to_session("D12:8") == 12

    def test_invalid_returns_none(self):
        for bad in ["", "1:3", "D1", "D:3", "DX:3", "D1:3 "]:
            assert dia_id_to_session(bad) is None


class TestStripAuditTags:
    def test_plain(self):
        assert strip_audit_tags("Luna") == "Luna"

    def test_audit_tag(self):
        assert strip_audit_tags("Counseling or mental health [LOCOMO-AUDIT]") == \
            "Counseling or mental health"

    def test_issues_tag(self):
        assert strip_audit_tags("foo [LOCOMO-ISSUES]") == "foo"

    def test_none_and_empty(self):
        assert strip_audit_tags(None) == ""
        assert strip_audit_tags("") == ""

    def test_int_answer_coerced(self):
        # 实测 V2 个别 answer 是裸数字（如年份 2023）
        assert strip_audit_tags(2023) == "2023"
        assert strip_audit_tags(0) == "0"


class TestApplyRename:
    def test_basic_replace(self):
        assert apply_rename("Caroline went home", {"Caroline": "Sarah"}) == "Sarah went home"

    def test_case_insensitive(self):
        assert apply_rename("caroline went home", {"Caroline": "Sarah"}) == "Sarah went home"
        assert apply_rename("CAROLINE went", {"Caroline": "Sarah"}) == "Sarah went"

    def test_word_boundary_protects_prefix(self):
        # "Ali" 不得吃掉 "Alice"（词边界保护）
        assert apply_rename("Alice went home", {"Ali": "Bob"}) == "Alice went home"
        assert apply_rename("Ali went home", {"Ali": "Bob"}) == "Bob went home"

    def test_word_boundary_protects_suffix(self):
        # "John" 不得吃掉 "Johnson"
        assert apply_rename("Johnson went", {"John": "Jack"}) == "Johnson went"
        assert apply_rename("John went", {"John": "Jack"}) == "Jack went"

    def test_both_speakers(self):
        text = "Caroline and Melanie talked."
        assert apply_rename(text, {"Caroline": "Sarah", "Melanie": "Jessica"}) == \
            "Sarah and Jessica talked."

    def test_longest_first_no_chain(self):
        # 长名优先 + 单遍替换：先替 Jessica 不应被后续 Jess 影响
        text = "Jess met Jessica"
        # 若按出现序短名优先：Jess->X 后 "Xica" 残留；长名优先保证 Jessica 整体命中
        out = apply_rename(text, {"Jess": "X", "Jessica": "Y"})
        assert "Y" in out  # Jessica 命中
        # 剩余的 Jess（独立词）被替为 X
        assert out.count("X") == 1

    def test_empty_map_or_text(self):
        assert apply_rename("Caroline", {}) == "Caroline"
        assert apply_rename("", {"Caroline": "Sarah"}) == ""

    def test_identity_no_change(self):
        # 换名映射里 v1==v2 的不进表（build_rename_map 过滤），apply_rename 本身遇同键同值也安全
        assert apply_rename("Caroline", {"Caroline": "Caroline"}) == "Caroline"


class TestMakeQid:
    def test_stable(self):
        assert make_qid("conv-26", "What?", 0) == make_qid("conv-26", "What?", 0)

    def test_unique_per_index(self):
        # 重复题（同 sample_id+question）靠 index 区分——resume 不误跳过
        assert make_qid("conv-48", "Same Q", 0) != make_qid("conv-48", "Same Q", 1)

    def test_different_conv_different_qid(self):
        assert make_qid("conv-26", "What?", 0) != make_qid("conv-30", "What?", 0)


class TestBuildRenameMap:
    def test_two_speakers(self):
        v1 = {"conversation": {"speaker_a": "Caroline", "speaker_b": "Melanie"}}
        v2 = {"conversation": {"speaker_a": "Sarah", "speaker_b": "Jessica"}}
        assert build_rename_map(v1, v2) == {"Caroline": "Sarah", "Melanie": "Jessica"}

    def test_identity_filtered(self):
        # 同名不进表（无意义）
        v1 = {"conversation": {"speaker_a": "Alice", "speaker_b": "Bob"}}
        v2 = {"conversation": {"speaker_a": "Alice", "speaker_b": "Bobby"}}
        assert build_rename_map(v1, v2) == {"Bob": "Bobby"}


class TestFilterByCategory:
    def test_single_int(self):
        qas = [LoCoMoQA("a", "q", 1), LoCoMoQA("b", "q", 5), LoCoMoQA("c", "q", 5)]
        assert [q.qid for q in filter_by_category(qas, 5)] == ["b", "c"]

    def test_iterable(self):
        qas = [LoCoMoQA("a", "q", 1), LoCoMoQA("b", "q", 2), LoCoMoQA("c", "q", 3)]
        assert {q.qid for q in filter_by_category(qas, {1, 3})} == {"a", "c"}


def test_locomo_qa_evidence_sessions():
    q = LoCoMoQA("x", "q", 1, evidence=["D1:3", "D2:8", "D1:9"])
    assert q.evidence_sessions == {1, 2}


# ---------------------------------------------------------------------------
# 合成三源（合成小数据，validate=False）
# ---------------------------------------------------------------------------


def _synthetic_base() -> dict:
    return {
        "sample_id": "conv-test",
        "conversation": {
            "speaker_a": "Alice", "speaker_b": "Bob",
            "session_1_date_time": "2:30 pm on 15 March, 2020",
            "session_1": [
                {"speaker": "Alice", "dia_id": "D1:1", "text": "I adopted a cat named Luna."},
                {"speaker": "Bob", "dia_id": "D1:2", "text": "Cute!",
                 "img_url": ["http://example.com/luna.jpg"]},
            ],
            "session_2_date_time": "10:00 am on 20 March, 2020",
            "session_2": [
                {"speaker": "Alice", "dia_id": "D2:1", "text": "Luna is growing fast."},
            ],
            # conv-26 风格的残桩：有 date_time 无 session 列表 -> 丢弃
            "session_3_date_time": "3:00 pm on 25 March, 2020",
        },
        "qa": [
            {"question": "What is Alice's cat's name?", "answer": "Luna", "category": 4},
            {"question": "When did Alice adopt Luna?", "answer": "15 March 2020", "category": 2},
            # adversarial：无 answer
            {"question": "What is Alice's dog's name?", "category": 5,
             "adversarial_answer": "there is no dog"},
        ],
        "event_summary": {}, "observation": {}, "session_summary": {},
    }


def _synthetic_caption() -> dict:
    # caption 变体：conversation 逐轮 text 与 base 一致，D1:2 多 moondream_caption
    base = _synthetic_base()
    cap = json.loads(json.dumps(base))
    for t in cap["conversation"]["session_1"]:
        if t["dia_id"] == "D1:2":
            t["moondream_caption"] = "a close-up photo of a cat"
    return cap


def _synthetic_v1() -> dict:
    # V1：speaker 换名（Alice->Alicia, Bob->Roberto），qa 带 evidence，问题用 V1 名
    return {
        "sample_id": "conv-test",
        "conversation": {"speaker_a": "Alicia", "speaker_b": "Roberto"},
        "qa": [
            {"question": "What is Alicia's cat's name?", "answer": "Luna",
             "evidence": ["D1:1"], "category": 4},
            {"question": "When did Alicia adopt Luna?", "answer": "15 March 2020",
             "evidence": ["D1:1", "D2:1"], "category": 2},
        ],
    }


@pytest.fixture
def tmp_three_sources(tmp_path):
    base = tmp_path / "base.json"
    cap = tmp_path / "cap.json"
    v1 = tmp_path / "v1.json"
    base.write_text(json.dumps([_synthetic_base()], ensure_ascii=False), encoding="utf-8")
    cap.write_text(json.dumps([_synthetic_caption()], ensure_ascii=False), encoding="utf-8")
    v1.write_text(json.dumps([_synthetic_v1()], ensure_ascii=False), encoding="utf-8")
    return base, cap, v1


class TestSynthesis:
    def test_timestamp_iso(self, tmp_three_sources):
        base, cap, v1 = tmp_three_sources
        docs = LoCoMoDataLoader(base, caption_path=cap, v1_source_path=v1,
                                cache_dir=None, validate=False).load()
        assert docs[0].sessions[0].timestamp_iso == "2020-03-15T14:30:00"
        assert docs[0].sessions[1].timestamp_iso == "2020-03-20T10:00:00"

    def test_stub_session_dropped(self, tmp_three_sources):
        base, cap, v1 = tmp_three_sources
        docs = LoCoMoDataLoader(base, caption_path=cap, v1_source_path=v1,
                                cache_dir=None, validate=False).load()
        # session_3 只有 date_time 无 turn-list -> 不应出现
        assert [s.session_id for s in docs[0].sessions] == [1, 2]

    def test_caption_migrated_by_dia_id(self, tmp_three_sources):
        base, cap, v1 = tmp_three_sources
        docs = LoCoMoDataLoader(base, caption_path=cap, v1_source_path=v1,
                                cache_dir=None, validate=False).load()
        s1 = docs[0].sessions[0]
        by_dia = {t.dia_id: t for t in s1.turns}
        assert by_dia["D1:2"].caption == "a close-up photo of a cat"
        assert by_dia["D1:1"].caption is None  # 无图轮无 caption

    def test_evidence_migrated_via_rename(self, tmp_three_sources):
        base, cap, v1 = tmp_three_sources
        docs = LoCoMoDataLoader(base, caption_path=cap, v1_source_path=v1,
                                cache_dir=None, validate=False).load()
        by_q = {q.question: q for q in docs[0].qa_list}
        # V1 "What is Alicia's cat's name?" 经换名 -> 匹配 V2 "Alice's cat's name"
        cat_q = by_q["What is Alice's cat's name?"]
        assert cat_q.evidence == ["D1:1"]
        assert cat_q.evidence_sessions == {1}
        when_q = by_q["When did Alice adopt Luna?"]
        assert when_q.evidence_sessions == {1, 2}

    def test_adversarial_no_answer(self, tmp_three_sources):
        base, cap, v1 = tmp_three_sources
        docs = LoCoMoDataLoader(base, caption_path=cap, v1_source_path=v1,
                                cache_dir=None, validate=False).load()
        adv = next(q for q in docs[0].qa_list if q.category == 5)
        assert adv.answer is None
        assert adv.adversarial_answer == "there is no dog"

    def test_qid_unique_per_qa(self, tmp_three_sources):
        base, cap, v1 = tmp_three_sources
        docs = LoCoMoDataLoader(base, caption_path=cap, v1_source_path=v1,
                                cache_dir=None, validate=False).load()
        qids = [q.qid for q in docs[0].qa_list]
        assert len(qids) == len(set(qids))

    def test_caption_mismatch_raises(self, tmp_path):
        # caption 变体某轮 text 与 base 不一致 -> 报错（D1 一致性约束）
        base = _synthetic_base()
        cap = json.loads(json.dumps(base))
        for t in cap["conversation"]["session_1"]:
            if t["dia_id"] == "D1:2":
                t["text"] = "DIFFERENT TEXT"
                t["moondream_caption"] = "x"
        bp = tmp_path / "b.json"; cp = tmp_path / "c.json"; vp = tmp_path / "v.json"
        bp.write_text(json.dumps([base]), encoding="utf-8")
        cp.write_text(json.dumps([cap]), encoding="utf-8")
        vp.write_text(json.dumps([_synthetic_v1()]), encoding="utf-8")
        with pytest.raises(ValueError, match="逐轮不一致"):
            LoCoMoDataLoader(bp, caption_path=cp, v1_source_path=vp,
                             cache_dir=None, validate=False).load()

    def test_category_drift_raises(self, tmp_path):
        # 类别分布不符 -> validate=True 报错
        base = _synthetic_base()
        bp = tmp_path / "b.json"; cp = tmp_path / "c.json"; vp = tmp_path / "v.json"
        bp.write_text(json.dumps([base]), encoding="utf-8")
        cp.write_text(json.dumps([_synthetic_caption()]), encoding="utf-8")
        vp.write_text(json.dumps([_synthetic_v1()]), encoding="utf-8")
        with pytest.raises(ValueError, match="类别分布漂移"):
            LoCoMoDataLoader(bp, caption_path=cp, v1_source_path=vp,
                             cache_dir=None, validate=True).load()

    def test_cache_roundtrip(self, tmp_three_sources):
        base, cap, v1 = tmp_three_sources
        cache = base.parent / "cache"
        docs1 = LoCoMoDataLoader(base, caption_path=cap, v1_source_path=v1,
                                 cache_dir=cache, validate=False).load()
        # 第二次走缓存
        docs2 = LoCoMoDataLoader(base, caption_path=cap, v1_source_path=v1,
                                 cache_dir=cache, validate=False).load()
        assert [d.sample_id for d in docs1] == [d.sample_id for d in docs2]
        assert docs2[0].sessions[0].timestamp_iso == "2020-03-15T14:30:00"

    def test_missing_file_raises(self, tmp_path):
        with pytest.raises(FileNotFoundError):
            LoCoMoDataLoader(tmp_path / "nope.json", caption_path=tmp_path / "c.json",
                             v1_source_path=tmp_path / "v.json",
                             cache_dir=None, validate=False).load()

    def test_unknown_caption_variant_raises(self):
        with pytest.raises(ValueError, match="未知 caption 变体"):
            LoCoMoDataLoader("x", caption_variant="blip")


# ---------------------------------------------------------------------------
# 真实全量数据（skipif 门控——数据未 copy 到 bench/locomo/data/ 则跳过）
# ---------------------------------------------------------------------------

_DATA_DIR = Path(__file__).resolve().parents[1] / "bench" / "locomo" / "data"
_REAL_BASE = _DATA_DIR / "locomo_v2" / "data" / "locomo_v2_base.json"
needs_real_data = pytest.mark.skipif(
    not _REAL_BASE.exists(), reason="LoCoMo 数据未 copy 到 bench/locomo/data（先跑 download_data）"
)


@needs_real_data
class TestRealDataset:
    def test_category_distribution_matches_spec(self):
        from collections import Counter
        docs = LoCoMoDataLoader(cache_dir=None, validate=True).load()
        dist = Counter()
        for d in docs:
            for q in d.qa_list:
                dist[q.category] += 1
        assert dict(sorted(dist.items())) == EXPECTED_CATEGORY_COUNTS
        assert sum(dist.values()) == 1922

    def test_caption_count_moondream(self):
        docs = LoCoMoDataLoader(caption_variant="moondream", cache_dir=None, validate=True).load()
        cap = sum(1 for d in docs for s in d.sessions for t in s.turns if t.caption)
        assert cap == EXPECTED_CAPTION_COUNT

    def test_evidence_hit_rate(self):
        docs = LoCoMoDataLoader(cache_dir=None, validate=True).load()
        total = sum(len(d.qa_list) for d in docs)
        with_ev = sum(1 for d in docs for q in d.qa_list if q.evidence)
        assert with_ev / total >= 0.95

    def test_all_qids_unique(self):
        docs = LoCoMoDataLoader(cache_dir=None, validate=True).load()
        qids = [q.qid for d in docs for q in d.qa_list]
        assert len(qids) == len(set(qids)) == 1922

    def test_sessions_and_turns_counts(self):
        docs = LoCoMoDataLoader(cache_dir=None, validate=True).load()
        assert sum(len(d.sessions) for d in docs) == 272
        assert sum(len(s.turns) for d in docs for s in d.sessions) == 5882

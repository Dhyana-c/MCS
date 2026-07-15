# -*- coding: utf-8 -*-
"""《黄金笼》评测数据集（golden_cage_corpus/qa.json）的构建与校验测试。"""

import importlib.util
import json
from pathlib import Path

import pytest

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "bench" / "golden_cage" / "scripts"
DATA_DIR = Path(__file__).resolve().parents[1] / "bench" / "golden_cage" / "data"
CORPUS_PATH = DATA_DIR / "golden_cage_corpus.json"
QA_PATH = DATA_DIR / "golden_cage_qa.json"


def _load_module(name: str):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS_DIR / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


builder = _load_module("build_corpus")
validator = _load_module("validate")


# ---------- corpus 切分 ----------


def test_split_scenes_basic():
    text = "## 第一章\n场景一内容。\n\n---\n\n场景二内容。\n"
    assert builder.split_scenes(text) == ["场景一内容。", "场景二内容。"]


def test_split_scenes_strips_heading_and_empty_segments():
    # 章标题行被剥掉；连续分隔符产生的空段被丢弃
    text = "## 第二章\n---\n---\n只有一个场景。\n---\n"
    assert builder.split_scenes(text) == ["只有一个场景。"]


def test_split_scenes_inline_dashes_not_split():
    # 行内 --- 或 ——（破折号）不触发切分，只有独立 --- 行才切
    text = "前半句---后半句。\n带——破折号的句子。\n---\n第二场景。"
    scenes = builder.split_scenes(text)
    assert len(scenes) == 2
    assert "前半句---后半句。" in scenes[0]


# ---------- normalize ----------


def test_normalize_unifies_quotes_and_whitespace():
    curly = "官方的说法是“谨慎推进”，是“分阶段验证”。"
    ascii_q = '官方的说法是"谨慎推进"，  是"分阶段验证"。'
    assert validator.normalize(curly) == validator.normalize(ascii_q)
    assert validator.normalize("a b\nc\t d") == "abcd"


# ---------- validate_cases 边界 ----------


@pytest.fixture()
def tiny_corpus():
    return {
        "第一章·场景01": {"body": "马库斯站在湖边。他说了一句话。"},
        "第一章·场景02": {"body": "林渊在运算中心看着屏幕。"},
    }


def _case(**kw):
    base = {
        "query": "测试问题？",
        "answer": "答案",
        "question_type": "inference_query",
        "evidence": [
            ("第一章·场景01", "马库斯站在湖边。"),
            ("第一章·场景02", "林渊在运算中心看着屏幕。"),
        ],
    }
    base.update(kw)
    return base


def test_validate_ok(tiny_corpus):
    assert validator.validate_cases([_case()], tiny_corpus) == []


def test_validate_fact_not_in_body(tiny_corpus):
    bad = _case(evidence=[("第一章·场景01", "不存在的句子。"), ("第一章·场景02", "林渊在运算中心看着屏幕。")])
    errors = validator.validate_cases([bad], tiny_corpus)
    assert any("不在" in e and "原文" in e for e in errors)


def test_validate_unknown_title(tiny_corpus):
    bad = _case(evidence=[("第九章·场景99", "马库斯站在湖边。"), ("第一章·场景02", "林渊在运算中心看着屏幕。")])
    errors = validator.validate_cases([bad], tiny_corpus)
    assert any("title 不在 corpus" in e for e in errors)


def test_validate_single_scene_rejected(tiny_corpus):
    # 两条证据同一场景 → 不算跨场景多跳
    bad = _case(evidence=[("第一章·场景01", "马库斯站在湖边。"), ("第一章·场景01", "他说了一句话。")])
    errors = validator.validate_cases([bad], tiny_corpus)
    assert any("跨" in e for e in errors)


def test_validate_null_with_evidence_rejected(tiny_corpus):
    bad = _case(question_type="null_query", answer="Insufficient information.")
    errors = validator.validate_cases([bad], tiny_corpus)
    assert any("null_query 不应有 evidence" in e for e in errors)


def test_validate_null_answer_enforced(tiny_corpus):
    bad = _case(question_type="null_query", answer="随便", evidence=[])
    errors = validator.validate_cases([bad], tiny_corpus)
    assert any("Insufficient information" in e for e in errors)


def test_validate_duplicate_query(tiny_corpus):
    errors = validator.validate_cases([_case(), _case()], tiny_corpus)
    assert any("query 重复" in e for e in errors)


def test_validate_bad_question_type(tiny_corpus):
    errors = validator.validate_cases([_case(question_type="what_query")], tiny_corpus)
    assert any("非法 question_type" in e for e in errors)


# ---------- 落盘数据集全量校验 ----------

needs_dataset = pytest.mark.skipif(
    not (CORPUS_PATH.exists() and QA_PATH.exists()),
    reason="golden_cage 数据集未生成",
)


@needs_dataset
def test_generated_dataset_valid():
    errors, dist = validator.validate_qa_file(QA_PATH, CORPUS_PATH)
    assert errors == []
    assert sum(dist.values()) == 150
    assert dist["inference_query"] == 50
    assert dist["comparison_query"] == 45
    assert dist["temporal_query"] == 35
    assert dist["null_query"] == 20


@needs_dataset
def test_corpus_scene_titles_unique_and_nonempty():
    docs = json.loads(CORPUS_PATH.read_text(encoding="utf-8"))
    titles = [d["title"] for d in docs]
    assert len(titles) == len(set(titles))
    assert all(d["body"].strip() for d in docs)
    # published_at 在章内按场景序严格递增（temporal 排序语义）
    by_chap = {}
    for d in docs:
        by_chap.setdefault(d["title"].split("·")[0], []).append(d["published_at"])
    for chap, times in by_chap.items():
        assert times == sorted(times), chap


@needs_dataset
def test_loader_compat():
    """bench.golden_cage.data.load 能直接加载该数据集（消费方兼容）。"""
    from bench.golden_cage.data import load

    docs, queries = load()
    assert len(docs) == 141
    assert len(queries) == 150
    doc_titles = {d.title for d in docs}
    for q in queries:
        # 所有 gold 文档都能在 corpus 中命中
        assert q.gold_doc_titles <= doc_titles
        assert q.query_id

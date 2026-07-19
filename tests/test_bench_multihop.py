"""MultiHop-RAG 评测框架测试。"""

from __future__ import annotations

import json
from unittest.mock import MagicMock

import pytest

from bench.multihop_rag import (
    MultiHopDataLoader,
    MultiHopQuery,
    aggregate_metrics,
    chunk_body,
    filter_queries,
    hit_at_k,
    map_at_k,
    mrr_at_k,
    recall_at_k,
    retrieved_docs,
)


@pytest.fixture
def tmp_corpus_qa(tmp_path):
    corpus = [
        {"title": "DocA", "body": "Alpha relates to Beta. More text here.",
         "source": "S", "url": "http://a"},
        {"title": "DocB", "body": "Beta connects to Gamma.", "source": "S", "url": "http://b"},
        {"title": "DocC", "body": "Distractor content.", "source": "S", "url": "http://c"},
    ]
    qa = [
        {"query": "How does Alpha reach Gamma?", "answer": "via Beta",
         "question_type": "inference_query",
         "evidence_list": [
             {"title": "DocA", "url": "http://a", "fact": "f1"},
             {"title": "DocB", "url": "http://b", "fact": "f2"},
         ]},
        {"query": "Is there info on Zeta?", "answer": "insufficient information",
         "question_type": "null_query", "evidence_list": []},
        {"query": "Compare DocC and a missing doc", "answer": "x",
         "question_type": "comparison_query",
         "evidence_list": [
             {"title": "DocC", "url": "http://c", "fact": "f3"},
             {"title": "DocMISSING", "url": "http://m", "fact": "f4"},
         ]},
    ]
    cp = tmp_path / "corpus.json"
    qp = tmp_path / "qa.json"
    cp.write_text(json.dumps(corpus), encoding="utf-8")
    qp.write_text(json.dumps(qa), encoding="utf-8")
    return str(cp), str(qp)


# ─── 7.1 加载 + 子集/query 过滤 ───────────────────────────────────────────────


def test_loader_full(tmp_corpus_qa):
    cp, qp = tmp_corpus_qa
    docs, queries = MultiHopDataLoader(cp, qp).load()
    assert len(docs) == 3
    assert len(queries) == 3  # 全量不过滤


def test_loader_subset_filters_unreachable(tmp_corpus_qa):
    cp, qp = tmp_corpus_qa
    docs, queries = MultiHopDataLoader(cp, qp, corpus_subset=2, seed=1).load()
    assert len(docs) == 2
    titles = {d.title for d in docs}
    # 保留的 query 证据必须全部可达
    for q in queries:
        assert q.gold_doc_titles <= titles
    # null_query 始终保留（证据为空）
    assert any(q.question_type == "null_query" for q in queries)


def test_loader_missing_file_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        MultiHopDataLoader(
            str(tmp_path / "nope.json"), str(tmp_path / "nope2.json")
        ).load()


def test_chunk_body_prepends_title_and_caps():
    body = "\n".join(f"Para {i}." for i in range(20))
    chunks = chunk_body("MyTitle", body, max_chunks=5)
    assert len(chunks) == 5
    assert chunks[0].startswith("MyTitle: ")


# ─── 7.2 Node → 来源文档映射 ─────────────────────────────────────────────────


def test_retrieved_docs_union_and_dedup():
    n1 = MagicMock()
    n1.extensions = {"source_tracking": {"sources": [
        MagicMock(doc_id="DocA"), MagicMock(doc_id="DocB"),
    ]}}
    n2 = MagicMock()
    n2.extensions = {"source_tracking": {"sources": [MagicMock(doc_id="DocA")]}}  # dup
    n3 = MagicMock()
    n3.extensions = {"source_tracking": {"sources": [MagicMock(doc_id="DocC")]}}
    assert retrieved_docs([n1, n2, n3]) == ["DocA", "DocB", "DocC"]


def test_retrieved_docs_empty():
    assert retrieved_docs([]) == []


# ─── 7.3 检索指标 ─────────────────────────────────────────────────────────────


def test_retrieval_metrics_known():
    gold = {"A", "B"}
    ranked = ["X", "A", "B", "Y"]  # A@2, B@3
    assert recall_at_k(ranked, gold, 2) == 0.5
    assert recall_at_k(ranked, gold, 3) == 1.0
    assert hit_at_k(ranked, gold, 2) == 1.0
    assert hit_at_k(ranked, gold, 1) == 0.0
    assert mrr_at_k(ranked, gold, 4) == 0.5
    assert abs(map_at_k(ranked, gold, 4) - ((0.5 + 2 / 3) / 2)) < 1e-9


def test_metrics_empty_edge_cases():
    assert recall_at_k([], {"A"}, 2) == 0.0
    assert recall_at_k(["A"], set(), 2) == 0.0
    assert mrr_at_k([], {"A"}, 2) == 0.0
    assert map_at_k([], {"A"}, 2) == 0.0


# ─── 7.4 聚合 + null_query 诊断 ──────────────────────────────────────────────


def test_aggregate_groups_and_null():
    results = [
        {"type": "inference_query", "gold": ["A", "B"], "ranked": ["A", "B"]},
        {"type": "comparison_query", "gold": ["C"], "ranked": ["X", "C"]},
        {"type": "null_query", "gold": [], "ranked": ["Z", "Y"]},
    ]
    agg = aggregate_metrics(results, [2])
    assert agg["overall"]["n"] == 2  # null 不计入
    assert "inference_query" in agg and "comparison_query" in agg
    assert agg["null_query"]["n"] == 1
    assert agg["null_query"]["avg_docs_retrieved"] == 2.0
    assert agg["inference_query"]["recall@2"] == 1.0


# ─── 7.x（5.7）--exclude-null ─────────────────────────────────────────────────


def test_filter_queries_excludes_null():
    qs = [
        MultiHopQuery("q1", "a", "inference_query"),
        MultiHopQuery("q2", "a", "null_query"),
        MultiHopQuery("q3", "a", "comparison_query"),
    ]
    assert len(filter_queries(qs, exclude_null=False)) == 3
    kept = filter_queries(qs, exclude_null=True)
    assert len(kept) == 2
    assert all(q.question_type != "null_query" for q in kept)

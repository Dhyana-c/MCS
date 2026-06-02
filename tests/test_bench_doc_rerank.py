"""文档级重排（bench-only）测试。覆盖 tasks 3.1–3.5。"""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest

from mcs.bench.doc_rerank import aggregate_docs, doc_rerank
from mcs.bench.multihop_rag import MultiHopEvalConfig, MultiHopEvalRunner
from mcs.core.graph import Node
from mcs.plugins.phase1.source_tracking import Source


def _node(name: str, content: str, doc: str, statements=None) -> Node:
    ext: dict = {
        "source_tracking": {
            "sources": [Source(doc_id=doc, chunk_id="0", content_hash="h")]
        }
    }
    if statements:
        ext["statements"] = {"items": list(statements)}
    return Node(id=f"{doc}_{name}", name=name, content=content, extensions=ext)


# ─── 3.1 节点→文档聚合 ────────────────────────────────────────────────────────


def test_aggregate_docs_groups_by_doc_id():
    nodes = [
        _node("A concept", "content a", "DocA"),
        _node("B concept", "content b", "DocB"),
        _node("A again", "more a", "DocA"),
    ]
    docs = aggregate_docs(nodes)
    assert set(docs) == {"DocA", "DocB"}
    assert docs["DocA"]["title"] == "DocA"
    assert len(docs["DocA"]["texts"]) == 2  # 两个节点聚合到同一文档
    assert docs["DocA"]["rank"] == 0  # 首次出现序


def test_aggregate_docs_collects_statements():
    nodes = [_node("X", "c", "DocA", statements=["X founded Acme"])]
    docs = aggregate_docs(nodes)
    assert any("Acme" in t for t in docs["DocA"]["texts"])


# ─── 3.2 文档级打分 + 重排/过滤/截断 ─────────────────────────────────────────


def test_doc_rerank_orders_by_relevance():
    gold = _node("Uber Q3 profitability", "Uber Q3 profitability gains", "UberDoc")
    distractor = _node("Manchester United", "football report", "SportsDoc")
    out = doc_rerank([distractor, gold], "Uber Q3 profitability numbers")
    assert out[0] == "UberDoc"  # 含查询词的文档排前（原序 distractor 在前）


def test_doc_rerank_title_weighted():
    # 命中标题(doc_id) 应比仅命中 content 得分更高
    in_title = _node("x", "unrelated body", "quantum computing")
    in_content = _node("y", "a note about quantum computing", "OtherDoc")
    out = doc_rerank([in_content, in_title], "quantum computing")
    assert out[0] == "quantum computing"


def test_doc_rerank_truncates_top_n():
    nodes = [
        _node("Tesla a", "Tesla", "DocA"),
        _node("Tesla b", "Tesla", "DocB"),
        _node("Tesla c", "Tesla", "DocC"),
    ]
    out = doc_rerank(nodes, "Tesla", top_n=2)
    assert len(out) == 2


def test_doc_rerank_filters_min_score():
    gold = _node("Tesla Model 3", "Tesla Model 3 output", "HitDoc")
    miss = _node("weather", "rain in berlin", "MissDoc")
    out = doc_rerank([gold, miss], "Tesla Model 3", min_score=0.5)
    assert "HitDoc" in out and "MissDoc" not in out


def test_doc_rerank_stable_for_equal_scores():
    # 与查询零重叠 → 全 0 分 → 保持原首次出现序
    nodes = [_node("aa", "x", "DocA"), _node("bb", "y", "DocB")]
    out = doc_rerank(nodes, "zzz_no_overlap_query")
    assert out == ["DocA", "DocB"]


# ─── 3.3 空召回 / 无 doc_id 透传 ─────────────────────────────────────────────


def test_doc_rerank_empty_passthrough():
    assert doc_rerank([], "anything") == []


def test_doc_rerank_no_doc_id_returns_empty():
    n = Node(id="n", name="x", content="", extensions={})
    assert doc_rerank([n], "anything") == []


# ─── 3.4 / 3.5 runner 集成：默认旁路 + 启用路由 + 与 --rerank 正交 ────────────


@pytest.fixture
def tmp_corpus_qa(tmp_path):
    corpus = [
        {"title": "DocA", "body": "Alpha Beta", "source": "S", "url": "u"},
        {"title": "DocB", "body": "Gamma", "source": "S", "url": "u"},
    ]
    qa = [
        {"query": "Alpha Beta", "answer": "x", "question_type": "inference_query",
         "evidence_list": [{"title": "DocA", "url": "u", "fact": "f"}]},
    ]
    cp = tmp_path / "c.json"
    qp = tmp_path / "q.json"
    cp.write_text(json.dumps(corpus), encoding="utf-8")
    qp.write_text(json.dumps(qa), encoding="utf-8")
    return str(cp), str(qp)


def _fake_build_factory():
    # query 返回：DocB 节点(原序在前、不相关) + DocA 节点(含查询词 Alpha Beta)
    def fake_build(docs, llm="deepseek", db_path="", max_chunks_per_doc=8, **kw):
        m = MagicMock()
        m.query.return_value = [
            _node("noise", "zzz", "DocB"),
            _node("Alpha Beta", "Alpha Beta concept", "DocA"),
        ]
        return m
    return fake_build


def test_config_doc_rerank_default_off():
    assert MultiHopEvalConfig().doc_rerank is False


def test_runner_doc_rerank_off_uses_node_order(tmp_corpus_qa, tmp_path):
    cp, qp = tmp_corpus_qa
    out = tmp_path / "out"
    cfg = MultiHopEvalConfig(
        corpus_path=cp, queries_path=qp, output_dir=str(out),
        db_path=str(tmp_path / "g.db"), doc_rerank=False,
    )
    with patch("mcs.bench.multihop_rag.build_shared_graph", side_effect=_fake_build_factory()):
        MultiHopEvalRunner(cfg).run()
    res = json.loads((out / "retrieval_results.json").read_text(encoding="utf-8"))
    ranked = next(iter(res.values()))["ranked"]
    assert ranked == ["DocB", "DocA"]  # 旁路：retrieved_docs 按节点 rank 序


def test_runner_doc_rerank_on_routes_through_doc_rerank(tmp_corpus_qa, tmp_path):
    cp, qp = tmp_corpus_qa
    out = tmp_path / "out"
    cfg = MultiHopEvalConfig(
        corpus_path=cp, queries_path=qp, output_dir=str(out),
        db_path=str(tmp_path / "g.db"), doc_rerank=True,
    )
    with patch("mcs.bench.multihop_rag.build_shared_graph", side_effect=_fake_build_factory()):
        MultiHopEvalRunner(cfg).run()
    res = json.loads((out / "retrieval_results.json").read_text(encoding="utf-8"))
    ranked = next(iter(res.values()))["ranked"]
    assert ranked[0] == "DocA"  # 文档级重排把含查询词的 DocA 排前

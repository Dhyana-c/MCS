"""MultiHop-RAG 检索指标计算。

按 question_type 与总体聚合 Hit@k / Recall@k / MAP@k / MRR@k。
"""

from __future__ import annotations

import statistics
from typing import Any


def retrieved_docs(nodes: list[Any]) -> list[str]:
    """把 query() 返回的节点（按 rank）映射成"按 rank 去重的来源文档列表"。

    一个概念节点可能来自多篇文档（merge 后）→ 取其来源并集。
    """
    seen: set[str] = set()
    ranked: list[str] = []
    for node in nodes:
        sources = (
            (getattr(node, "extensions", {}) or {})
            .get("source_tracking", {})
            .get("sources", [])
        )
        for s in sources:
            doc = s.doc_id if hasattr(s, "doc_id") else (
                s.get("doc_id") if isinstance(s, dict) else None
            )
            if doc and doc not in seen:
                seen.add(doc)
                ranked.append(doc)
    return ranked


def recall_at_k(ranked: list[str], gold: set[str], k: int) -> float:
    if not gold:
        return 0.0
    return len(set(ranked[:k]) & gold) / len(gold)


def hit_at_k(ranked: list[str], gold: set[str], k: int) -> float:
    """是否在 top-k 命中至少一个 gold 文档。"""
    if not gold:
        return 0.0
    return 1.0 if (set(ranked[:k]) & gold) else 0.0


def map_at_k(ranked: list[str], gold: set[str], k: int) -> float:
    if not gold:
        return 0.0
    hits = 0
    score = 0.0
    for i, d in enumerate(ranked[:k], 1):
        if d in gold:
            hits += 1
            score += hits / i
    return score / min(len(gold), k)


def mrr_at_k(ranked: list[str], gold: set[str], k: int) -> float:
    for i, d in enumerate(ranked[:k], 1):
        if d in gold:
            return 1.0 / i
    return 0.0


def _mean(xs: list[float]) -> float:
    return statistics.fmean(xs) if xs else 0.0


def aggregate_metrics(
    results: list[dict], k_values: list[int]
) -> dict[str, dict]:
    """按 question_type 与总体聚合检索指标；null_query 单独诊断。"""
    buckets: dict[str, list[dict]] = {}
    null_docs: list[int] = []
    for r in results:
        if r["type"] == "null_query":
            null_docs.append(len(r["ranked"]))
            continue
        buckets.setdefault(r["type"], []).append(r)
        buckets.setdefault("overall", []).append(r)

    out: dict[str, dict] = {}
    for name, rs in buckets.items():
        m: dict[str, float] = {"n": len(rs)}
        for k in k_values:
            golds = [set(r["gold"]) for r in rs]
            ranks = [r["ranked"] for r in rs]
            m[f"hit@{k}"] = _mean([hit_at_k(rk, g, k) for rk, g in zip(ranks, golds)])
            m[f"recall@{k}"] = _mean(
                [recall_at_k(rk, g, k) for rk, g in zip(ranks, golds)]
            )
            m[f"map@{k}"] = _mean([map_at_k(rk, g, k) for rk, g in zip(ranks, golds)])
            m[f"mrr@{k}"] = _mean([mrr_at_k(rk, g, k) for rk, g in zip(ranks, golds)])
        out[name] = m
    out["null_query"] = {
        "n": len(null_docs),
        "avg_docs_retrieved": _mean([float(x) for x in null_docs]),
    }
    return out
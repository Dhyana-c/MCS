"""bench MultiHop 评测脚本的共享逻辑（**非入口**，被 build/test/eval 复用）。

统一：env 装配（固定 deepseek-chat）、文档子集选择、**可达 query 过滤**、查询循环 +
**文档级重排（默认开）** + 指标。建图走 builder.build_shared_graph（已含幂等续跑 +
事实边去重 + judge_relations 截断兜底）。
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sqlite3
import sys
import time
from pathlib import Path

_SCRIPTS = Path(__file__).resolve().parent
PROJECT_ROOT = _SCRIPTS.parent.parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


# === env / 日志 / 参数 ===


def setup_env() -> None:
    """UTF-8 stdout + 载入 .env + 固定 deepseek-chat。"""
    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    envf = PROJECT_ROOT / ".env"
    if envf.exists():
        for line in envf.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())
    os.environ["DEEPSEEK_MODEL"] = "deepseek-chat"
    os.environ.setdefault("MCS_NO_SUMMARY_REGEN", "1")


def init_logging(out_dir: Path, logname: str) -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
        handlers=[
            logging.FileHandler(out_dir / logname, encoding="utf-8", mode="a"),
            logging.StreamHandler(),
        ],
    )
    logging.getLogger("jieba").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)


def add_build_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--docs", type=int, default=609, help="建图文档数（默认 609 全量）")
    p.add_argument(
        "--token-budget", type=int, default=16000, help="核心不变量阈值 T（默认 16000）"
    )
    p.add_argument("--output", required=True, help="输出目录（含 graph.db / 日志 / 指标）")
    p.add_argument(
        "--no-resume", action="store_true", help="不续跑：先清空 graph.db 重建"
    )


def add_query_args(p: argparse.ArgumentParser) -> None:
    p.add_argument("--queries", type=int, default=0, help="评测 query 数（0=全部可达）")
    p.add_argument(
        "--doc-rerank",
        choices=["lexical", "llm", "none"],
        default="lexical",
        help="文档级重排（默认 lexical 词法、零额外 LLM；llm 语义重排；none 关闭）",
    )
    p.add_argument(
        "--rerank-top-n",
        type=int,
        default=0,
        help="节点级重排截断 top-N（0=不截断/放全量，默认 0）",
    )


def db_path(out_dir: str | Path) -> Path:
    return Path(out_dir) / "graph.db"


# === 建图 / 装载 ===


def build_graph(
    n_docs: int, out_dir: str, token_budget: int, resume: bool = True,
    rerank_top_n: int = 0,
):
    """建图（whole_doc, deepseek-chat），返回 (mcs, db_path)。

    ``rerank_top_n=0`` → 节点级重排不截断（放全量）。
    """
    from bench.multihop_rag.builder import build_shared_graph
    from bench.multihop_rag.data import MultiHopDataLoader

    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    db = db_path(out)
    if not resume and db.exists():
        db.unlink()
    docs, _ = MultiHopDataLoader().load()
    docs = docs[:n_docs]
    print(f"建图：{len(docs)} 篇 @ T={token_budget} → {db}")
    mcs = build_shared_graph(
        docs, "deepseek", str(db), whole_doc=True, token_budget=token_budget,
        record_path=str(out / "llm_calls.jsonl"),
        rerank=True, rerank_top_n=(rerank_top_n or None),
    )
    return mcs, db


def load_graph(out_dir: str, token_budget: int, rerank_top_n: int = 0):
    """从已有 graph.db 装载 query-ready 的 mcs，返回 (mcs, db_path)。

    ``rerank_top_n=0`` → 节点级重排不截断（放全量）。
    """
    from bench.multihop_rag.builder import _make_mcs

    db = db_path(out_dir)
    if not db.exists():
        raise SystemExit(f"未找到图库 {db}（先用 build.py / eval.py 建图）")
    mcs = _make_mcs(
        "deepseek", str(db), token_budget=token_budget,
        record_path=str(Path(out_dir) / "llm_calls_query.jsonl"),
        rerank=True, rerank_top_n=(rerank_top_n or None),
    )
    return mcs, db


def health_check(mcs, token_budget: int) -> None:
    """打印 dual-edge 体检（节点 / 边 / 不变量 / 重复事实边）。"""
    from collections import Counter

    from mcs.core.token_budget import TokenBudget

    store = mcs.store
    nodes = store.get_all_nodes()
    edges = store.get_all_edges()
    facts = [e for e in edges if e.kind == "fact"]
    hier = [e for e in edges if e.kind == "hierarchy"]
    roles: dict[str, int] = {}
    for n in nodes:
        roles[n.role] = roles.get(n.role, 0) + 1
    print("\n" + "=" * 60 + "\nDUAL-EDGE 体检\n" + "=" * 60)
    print(
        f"节点 {len(nodes)} {roles}  边 {len(edges)}"
        f"（层级 {len(hier)} / 事实 {len(facts)}）"
    )
    tb = TokenBudget(token_budget)
    viol = sum(
        1
        for n in nodes
        if tb.estimate_node(n)
        + sum(tb.estimate_node(k) for k in store.get_out_hierarchy(n.id))
        > tb.T
    )
    print(f"fanout 口径不变量 ≤ T={token_budget}: {'✓ 全过' if not viol else f'⚠ {viol} 违反'}")
    dup = sum(
        v - 1
        for v in Counter(
            (e.source_id, e.target_id, e.label) for e in facts
        ).values()
        if v > 1
    )
    print(f"重复事实边: {dup}")


# === 查询评测 ===


def _built_titles(db: Path) -> set[str]:
    conn = sqlite3.connect(str(db))
    try:
        return {
            r[0] for r in conn.execute("SELECT DISTINCT doc_id FROM document_chunks")
        }
    finally:
        conn.close()


def _make_reranker(mode: str):
    """返回 (nodes, query) -> ranked_doc_ids 的重排函数。"""
    from bench.multihop_rag.metrics import retrieved_docs

    if mode == "none":
        return lambda nodes, q: retrieved_docs(nodes)
    if mode == "llm":
        from bench.plugins.doc_rerank import llm_doc_rerank

        return lambda nodes, q: llm_doc_rerank(nodes, q)
    from bench.plugins.doc_rerank import doc_rerank

    return lambda nodes, q: doc_rerank(nodes, q)


def run_queries(
    mcs, db: Path, out_dir: str, n_queries: int, doc_rerank: str, token_budget: int
):
    """可达过滤 + 查询 + 文档级重排 + 指标；写 metrics.json，返回 metrics。"""
    from bench.multihop_rag.data import MultiHopDataLoader, filter_queries
    from bench.multihop_rag.metrics import aggregate_metrics

    built = _built_titles(db)
    _, queries = MultiHopDataLoader().load()
    queries = filter_queries(queries, exclude_null=True)  # null 无 gold，不计 hit@k
    reachable = [
        q for q in queries if q.gold_doc_titles and q.gold_doc_titles <= built
    ]
    selected = reachable[:n_queries] if n_queries else reachable
    print(
        f"已建 {len(built)} 篇；可达 query {len(reachable)}；"
        f"本次评测 {len(selected)}（doc_rerank={doc_rerank}）"
    )
    if not selected:
        print("⚠ 无可达 query。")
        return {}
    rerank = _make_reranker(doc_rerank)

    results: list[dict] = []
    t0 = time.time()
    for i, q in enumerate(selected, 1):
        try:
            res = mcs.query(q.query)
            nodes = (
                res.nodes if hasattr(res, "nodes")
                else (res if isinstance(res, list) else [])
            )
        except Exception as e:  # 单 query 失败不中断
            print(f"  query 失败 {q.query_id}: {e}")
            nodes = []
        ranked = rerank(nodes, q.query)
        results.append(
            {"type": q.question_type, "gold": sorted(q.gold_doc_titles), "ranked": ranked}
        )
        if i % 10 == 0 or i == len(selected):
            print(f"  {i}/{len(selected)} ({time.time() - t0:.0f}s)")

    metrics = aggregate_metrics(results, [2, 4, 10])
    _print_metrics(metrics, len(selected), token_budget, doc_rerank)
    (Path(out_dir) / "metrics.json").write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"指标已写 {Path(out_dir) / 'metrics.json'}（耗时 {time.time() - t0:.0f}s）")
    return metrics


def _print_metrics(metrics: dict, n: int, token_budget: int, doc_rerank: str) -> None:
    print("\n" + "=" * 60)
    print(f"检索指标（文档级，{n} query，T={token_budget}，doc_rerank={doc_rerank}）")
    print("=" * 60)
    for name in ["overall", "inference_query", "comparison_query", "temporal_query"]:
        m = metrics.get(name)
        if not m:
            continue
        parts = "  ".join(f"{k}={v:.3f}" for k, v in m.items() if k != "n")
        print(f"[{name} n={m['n']}]\n   {parts}")

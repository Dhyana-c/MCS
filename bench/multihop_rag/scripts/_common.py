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
    from bench._env import load_dotenv

    if sys.platform == "win32":
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    load_dotenv(PROJECT_ROOT / ".env")
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
    rerank_top_n: int = 0, llm: str = "deepseek", llm_config: dict | None = None,
):
    """建图（whole_doc），返回 (mcs, db_path)。

    ``rerank_top_n=0`` → 节点级重排不截断（放全量）。``llm``/``llm_config``
    指定后端与配置（默认 deepseek 基线不变）。
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
        docs, llm, str(db), whole_doc=True, token_budget=token_budget,
        record_path=str(out / "llm_calls.jsonl"),
        rerank=True, rerank_top_n=(rerank_top_n or None),
        llm_config=llm_config,
    )
    return mcs, db


def load_graph(
    out_dir: str, token_budget: int, rerank_top_n: int = 0,
    llm: str = "deepseek", llm_config: dict | None = None,
):
    """从已有 graph.db 装载 query-ready 的 mcs，返回 (mcs, db_path)。

    ``rerank_top_n=0`` → 节点级重排不截断（放全量）。``llm``/``llm_config``
    指定后端与配置（默认 deepseek 基线不变）。
    """
    from bench.multihop_rag.builder import _make_mcs

    db = db_path(out_dir)
    if not db.exists():
        raise SystemExit(f"未找到图库 {db}（先用 build.py / eval.py 建图）")
    mcs = _make_mcs(
        llm, str(db), token_budget=token_budget,
        record_path=str(Path(out_dir) / "llm_calls_query.jsonl"),
        rerank=True, rerank_top_n=(rerank_top_n or None),
        llm_config=llm_config,
    )
    return mcs, db


def health_check(mcs, token_budget: int) -> None:
    """打印 dual-edge 体检（节点 / 边 / 不变量 / 重复事实边）。"""
    from collections import Counter

    from mcs.core.token_budget import TokenBudget

    store = mcs.store
    nodes = store.get_all_nodes()
    edges = store.get_all_edges()
    assoc = [e for e in edges if e.type == "关联"]
    mutex = [e for e in edges if e.type == "互斥"]
    classes: dict[str, int] = {}
    for n in nodes:
        classes[n.node_class] = classes.get(n.node_class, 0) + 1
    print("\n" + "=" * 60 + "\n统一图模型 体检\n" + "=" * 60)
    print(
        f"节点 {len(nodes)} {classes}  边 {len(edges)}"
        f"（关联 {len(assoc)} / 互斥 {len(mutex)}）"
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
        for v in Counter((e.source_id, e.target_id) for e in assoc).values()
        if v > 1
    )
    print(f"重复关联边: {dup}")


# === 查询评测 ===


def _built_titles(db: Path) -> set[str]:
    conn = sqlite3.connect(str(db))
    try:
        return {
            r[0] for r in conn.execute("SELECT DISTINCT doc_id FROM document_chunks")
        }
    finally:
        conn.close()


def _count_llm_calls(path: Path) -> int:
    """统计 LLM 调用记录文件行数（用于配额监控）。文件不存在返回 0。"""
    if not path.exists():
        return 0
    with open(path, encoding="utf-8") as f:
        return sum(1 for _ in f)


def _make_reranker(mode: str, llm_config: dict | None = None):
    """返回 (nodes, query) -> ranked_doc_ids 的重排函数。"""
    from bench.multihop_rag.metrics import retrieved_docs

    if mode == "none":
        return lambda nodes, q: retrieved_docs(nodes)
    if mode == "llm":
        from bench.plugins.doc_rerank import llm_doc_rerank

        return lambda nodes, q: llm_doc_rerank(nodes, q, llm_config=llm_config)
    from bench.plugins.doc_rerank import doc_rerank

    return lambda nodes, q: doc_rerank(nodes, q)


def run_queries(
    mcs, db: Path, out_dir: str, n_queries: int, doc_rerank: str, token_budget: int,
    llm_config: dict | None = None, restart: bool = False,
):
    """可达过滤 + 查询 + 文档级重排 + 指标；写 metrics.json，返回 metrics。

    支持 query 级断点续跑：每完成一个 query 追加到 ``results.jsonl``（含
    ``query_id``），重跑时按 ``query_id`` 跳过已完成的，用全量累积结果算指标。
    ``restart=True`` 清空 ``results.jsonl`` 重新评测。
    """
    from bench.multihop_rag.data import MultiHopDataLoader, filter_queries
    from bench.multihop_rag.metrics import aggregate_metrics

    out = Path(out_dir)
    results_file = out / "results.jsonl"

    built = _built_titles(db)
    _, queries = MultiHopDataLoader().load()
    queries = filter_queries(queries, exclude_null=True)  # null 无 gold，不计 hit@k
    reachable = [
        q for q in queries if q.gold_doc_titles and q.gold_doc_titles <= built
    ]
    selected = reachable[:n_queries] if n_queries else reachable

    # 续跑：读取已完成的 query 结果（restart 时清空重来）
    done: dict[str, dict] = {}
    if restart and results_file.exists():
        results_file.unlink()
    if results_file.exists():
        for line in results_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                done[rec["query_id"]] = rec
            except Exception:
                continue
    todo = [q for q in selected if q.query_id not in done]
    print(
        f"已建 {len(built)} 篇；可达 query {len(reachable)}；"
        f"本次评测 {len(selected)}（已完成 {len(done)}，待跑 {len(todo)}，"
        f"doc_rerank={doc_rerank}）"
    )
    if not selected:
        print("⚠ 无可达 query。")
        return {}
    rerank = _make_reranker(doc_rerank, llm_config=llm_config)

    # 追加模式打开 results.jsonl，逐 query 持久化（断点 / 配额耗尽不丢）
    out.mkdir(parents=True, exist_ok=True)
    fh = open(results_file, "a", encoding="utf-8")
    quota = int((llm_config or {}).get("quota", 0))  # 0=不限配额
    llm_log = out / "llm_calls_query.jsonl"
    base_calls = _count_llm_calls(llm_log)  # 续跑前的历史调用（本次增量基线）
    t0 = time.time()
    processed = 0
    consecutive_failures = 0
    FAILURE_LIMIT = 3  # 连续失败熔断阈值（疑似配额耗尽 / 端点不可用）
    stop_reason = None
    for q in todo:
        try:
            res = mcs.query(q.query)
            nodes = (
                res.nodes if hasattr(res, "nodes")
                else (res if isinstance(res, list) else [])
            )
            ranked = rerank(nodes, q.query)
        except Exception as e:  # 单 query 失败不中断、不写入（续跑可重试）
            print(f"  query 失败 {q.query_id}: {e}")
            consecutive_failures += 1
            if consecutive_failures >= FAILURE_LIMIT:
                stop_reason = (
                    f"连续 {consecutive_failures} 个 query 失败，疑似配额耗尽 / 端点不可用"
                )
                break
            continue
        rec = {
            "query_id": q.query_id,
            "type": q.question_type,
            "gold": sorted(q.gold_doc_titles),
            "ranked": ranked,
        }
        fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        fh.flush()
        done[q.query_id] = rec
        consecutive_failures = 0
        processed += 1
        if processed % 10 == 0 or processed == len(todo):
            # 本次 session 端点消耗 = 新增内部 LLM 调用 + 新增重排（processed）。
            # 用 session 基线 base_calls 扣除续跑历史，避免历史调用累积导致续跑时
            # quota 立即触发、剩余 query 跑不动。
            used = ((_count_llm_calls(llm_log) - base_calls) + processed) if quota else 0
            quota_msg = f"，本次端点调用 {used}/{quota}" if quota else ""
            print(f"  进度 {len(done)}/{len(selected)} ({time.time() - t0:.0f}s{quota_msg})")
            if quota and used >= quota:
                stop_reason = f"本次 session 端点调用达预算 {quota}（实际 {used}）"
                break
    fh.close()
    if stop_reason:
        print(f"\n⚠ 提前停止：{stop_reason}")

    # 全量累积结果算指标（含续跑的历史，部分完成时也输出阶段性指标）
    all_results = [done[q.query_id] for q in selected if q.query_id in done]
    metrics = aggregate_metrics(all_results, [2, 4, 10])
    _print_metrics(metrics, len(all_results), token_budget, doc_rerank)
    (out / "metrics.json").write_text(
        json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"指标已写 {out / 'metrics.json'}（累计 {len(all_results)} query）")
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

"""MultiHop-RAG 评测运行器。

提供完整的评测流程：数据加载 → 图构建 → 查询 → 指标计算。
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Token 估算常量
_TOKENS_IN_PER_CHUNK = 7500
_TOKENS_OUT_PER_CHUNK = 1500
_PRICE_IN_PER_M = 0.5  # ¥/1M（deepseek-chat cache-miss 近似）
_PRICE_OUT_PER_M = 2.0  # ¥/1M


def _ensure_utf8_stdout() -> None:
    """stdout 切 UTF-8 + errors='replace'，避免 Windows GBK 控制台遇非 GBK 字符崩溃。"""
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def _maybe_load_dotenv() -> None:
    """若存在 .env（项目根或当前目录），把其中的键值灌进环境变量。"""
    for p in (Path("D:/code/mcs/.env"), Path(".env")):
        if not p.exists():
            continue
        for line in p.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                os.environ.setdefault(k.strip(), v.strip())
        return


from bench.multihop_rag.builder import build_shared_graph, chunk_body
from bench.multihop_rag.data import (
    DEFAULT_CORPUS,
    DEFAULT_QA,
    MultiHopDataLoader,
    filter_queries,
)
from bench.multihop_rag.metrics import aggregate_metrics, retrieved_docs


@dataclass
class MultiHopEvalConfig:
    corpus_path: str = DEFAULT_CORPUS
    queries_path: str = DEFAULT_QA
    corpus_subset: int | None = None
    llm_backend: str = "deepseek"
    token_budget: int = 8000  # 核心不变量阈值 T
    db_path: str = "./multihop_bench.db"
    output_dir: str = "./multihop_output"
    k_values: list[int] = field(default_factory=lambda: [2, 4, 10])
    max_chunks_per_doc: int = 8
    whole_doc: bool = False  # 整篇摄入（不切块）
    resume: bool = True
    dry_run: bool = False
    seed: int = 42
    exclude_null: bool = False  # 排除 null_query
    rerank: bool = True  # 节点级相关性重排
    rerank_top_n: int | None = 50
    rerank_min_score: float = 0.0
    max_accumulated_nodes: int | None = None
    max_rounds: int | None = None
    doc_rerank: bool = False  # 文档级重排（bench-only）
    doc_rerank_top_n: int | None = None


class MultiHopEvalRunner:
    def __init__(self, config: MultiHopEvalConfig | None = None):
        self.config = config or MultiHopEvalConfig()

    def run(self) -> dict[str, dict]:
        _ensure_utf8_stdout()
        from bench.plugins.doc_rerank import doc_rerank

        cfg = self.config
        out = Path(cfg.output_dir)
        out.mkdir(parents=True, exist_ok=True)

        loader = MultiHopDataLoader(
            cfg.corpus_path, cfg.queries_path, cfg.corpus_subset, cfg.seed
        )
        docs, queries = loader.load()
        queries = filter_queries(queries, cfg.exclude_null)
        suffix = "（已排除 null_query）" if cfg.exclude_null else ""
        print(f"语料 {len(docs)} 篇文档, {len(queries)} 个可达 query{suffix}")
        if cfg.rerank:
            print(
                f"重排已启用：scorer=lexical top_n={cfg.rerank_top_n} "
                f"min_score={cfg.rerank_min_score}"
            )
        if cfg.doc_rerank:
            print(f"文档级重排已启用（bench-only）：top_n={cfg.doc_rerank_top_n}")

        # 构建（或复用）共享图
        print("构建共享图（已摄入的会自动跳过）…")
        if cfg.whole_doc:
            print("整篇摄入模式：每篇文档作为单个单元（不切块），文本 100% 覆盖")
        mcs = build_shared_graph(
            docs,
            cfg.llm_backend,
            cfg.db_path,
            cfg.max_chunks_per_doc,
            whole_doc=cfg.whole_doc,
            token_budget=cfg.token_budget,
            record_path=str(out / "llm_calls.jsonl"),
            rerank=cfg.rerank,
            rerank_top_n=cfg.rerank_top_n,
            rerank_min_score=cfg.rerank_min_score,
            max_accumulated_nodes=cfg.max_accumulated_nodes,
            max_rounds=cfg.max_rounds,
        )

        # 断点续跑：复用已落盘的检索结果
        results_file = out / "retrieval_results.json"
        results: dict[str, dict] = {}
        if cfg.resume and results_file.exists():
            try:
                results = json.loads(results_file.read_text(encoding="utf-8"))
            except Exception:
                logger.warning("无法读取已有 retrieval_results.json，从头开始")
        done = set(results)

        def _persist() -> None:
            results_file.write_text(
                json.dumps(results, ensure_ascii=False), encoding="utf-8"
            )

        total = len(queries)
        for i, q in enumerate(queries, 1):
            if q.query_id in done:
                continue
            try:
                result = mcs.query(q.query)
                if isinstance(result, list):
                    nodes = result
                elif hasattr(result, "nodes"):
                    nodes = result.nodes  # Subgraph
                else:
                    nodes = []
            except Exception:
                logger.exception("query 失败: %s", q.query_id)
                nodes = []
            if cfg.doc_rerank:
                ranked = doc_rerank(nodes, q.query, top_n=cfg.doc_rerank_top_n)
            else:
                ranked = retrieved_docs(nodes)
            results[q.query_id] = {
                "type": q.question_type,
                "gold": sorted(q.gold_doc_titles),
                "ranked": ranked,
            }
            if i % 20 == 0 or i == total:
                print(f"  query {i}/{total}")
            _persist()

        mcs.shutdown()

        metrics = aggregate_metrics(list(results.values()), cfg.k_values)
        self._print_metrics(metrics)
        (out / "metrics.json").write_text(
            json.dumps(metrics, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        return metrics

    def dry_run(self) -> dict[str, Any]:
        _ensure_utf8_stdout()
        cfg = self.config
        loader = MultiHopDataLoader(
            cfg.corpus_path, cfg.queries_path, cfg.corpus_subset, cfg.seed
        )
        docs, queries = loader.load()
        total_chunks = sum(
            len(chunk_body(d.title, d.body, cfg.max_chunks_per_doc)) for d in docs
        )
        in_tok = total_chunks * _TOKENS_IN_PER_CHUNK
        out_tok = total_chunks * _TOKENS_OUT_PER_CHUNK
        cost = in_tok * _PRICE_IN_PER_M / 1e6 + out_tok * _PRICE_OUT_PER_M / 1e6
        est = {
            "docs": len(docs),
            "queries": len(queries),
            "total_chunks": total_chunks,
            "build_tokens_estimated": in_tok + out_tok,
            "build_cost_cny_estimated": round(cost, 2),
            "note": "仅首建图成本；query 阶段只走查询管线，成本低得多",
        }
        print("\n=== MultiHop-RAG Dry Run（首建图估算）===")
        for k, v in est.items():
            print(f"  {k}: {v}")
        return est

    @staticmethod
    def _print_metrics(metrics: dict[str, dict]) -> None:
        print("\n=== MultiHop-RAG 检索指标（文档级）===")
        for name in ["overall", "inference_query", "comparison_query", "temporal_query"]:
            m = metrics.get(name)
            if not m:
                continue
            parts = " ".join(
                f"{key}={val:.3f}"
                for key, val in m.items()
                if key != "n"
            )
            print(f"  [{name} n={m['n']}] {parts}")
        nq = metrics.get("null_query", {})
        if nq:
            print(
                f"  [null_query n={nq.get('n', 0)}] "
                f"avg_docs_retrieved={nq.get('avg_docs_retrieved', 0):.2f}"
            )


# ─── CLI 入口 ───────────────────────────────────────────────────────────────


def main() -> None:
    parser = argparse.ArgumentParser(description="MCS MultiHop-RAG 检索评测")
    parser.add_argument("--corpus", default=DEFAULT_CORPUS)
    parser.add_argument("--queries", default=DEFAULT_QA)
    parser.add_argument(
        "--corpus-subset", type=int, default=0, help="采样 N 篇文档（0=全量）"
    )
    parser.add_argument("--llm", choices=["deepseek", "claude", "ollama"], default="deepseek")
    parser.add_argument(
        "--token-budget",
        type=int,
        default=8000,
        help="核心不变量阈值 T（如 32000）；建图守门与查询子图共用",
    )
    parser.add_argument("--db", default="./multihop_bench.db")
    parser.add_argument("--output", default="./multihop_output")
    parser.add_argument(
        "--k", default="2,4,10", help="逗号分隔的 k 列表，如 2,4,10"
    )
    parser.add_argument("--max-chunks", type=int, default=8)
    parser.add_argument(
        "--whole-doc",
        action="store_true",
        help="整篇摄入（不切块）：标题+正文作为单个单元，文本 100%% 覆盖（长文档需调大 OLLAMA_NUM_CTX）",
    )
    parser.add_argument("--no-resume", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--exclude-null",
        action="store_true",
        help="排除 null_query，只评非 null 的可达 query",
    )
    parser.add_argument(
        "--no-rerank",
        action="store_true",
        help="关闭相关性重排（默认开；重排为查询侧 lexical、复用现有图、不重建）",
    )
    parser.add_argument(
        "--rerank-top-n",
        type=int,
        default=50,
        help="重排后截断 top-N（0 = 不截断；默认 50）",
    )
    parser.add_argument(
        "--rerank-min-score",
        type=float,
        default=0.0,
        help="重排过滤阈值，低于该分的节点被丢弃（默认 0.0 不误杀）",
    )
    parser.add_argument(
        "--max-accumulated-nodes",
        type=int,
        default=0,
        help="放宽遍历累积节点上限（0=用默认 1000；广召回时调大）",
    )
    parser.add_argument(
        "--max-rounds",
        type=int,
        default=0,
        help="放宽遍历轮数（0=用默认 5；广召回时调大，如 8）",
    )
    parser.add_argument(
        "--doc-rerank",
        action="store_true",
        help="启用文档级重排（bench-only，对候选文档直接打分排序，与 --rerank 正交）",
    )
    parser.add_argument(
        "--doc-rerank-top-n",
        type=int,
        default=0,
        help="文档级重排截断 top-N（0=不截断）",
    )
    args = parser.parse_args()

    _maybe_load_dotenv()
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    cfg = MultiHopEvalConfig(
        corpus_path=args.corpus,
        queries_path=args.queries,
        corpus_subset=args.corpus_subset if args.corpus_subset > 0 else None,
        llm_backend=args.llm,
        token_budget=args.token_budget,
        db_path=args.db,
        output_dir=args.output,
        k_values=[int(x) for x in args.k.split(",") if x.strip()],
        max_chunks_per_doc=args.max_chunks,
        whole_doc=args.whole_doc,
        resume=not args.no_resume,
        dry_run=args.dry_run,
        exclude_null=args.exclude_null,
        rerank=not args.no_rerank,
        rerank_top_n=args.rerank_top_n if args.rerank_top_n > 0 else None,
        rerank_min_score=args.rerank_min_score,
        max_accumulated_nodes=args.max_accumulated_nodes if args.max_accumulated_nodes > 0 else None,
        max_rounds=args.max_rounds if args.max_rounds > 0 else None,
        doc_rerank=args.doc_rerank,
        doc_rerank_top_n=args.doc_rerank_top_n if args.doc_rerank_top_n > 0 else None,
    )
    runner = MultiHopEvalRunner(cfg)
    if cfg.dry_run:
        runner.dry_run()
    else:
        runner.run()


if __name__ == "__main__":
    main()

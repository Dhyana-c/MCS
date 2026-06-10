"""分块查询评测脚本 — 从已有 DB 加载 MCS，按 500 个 query 一块跑查询。

用法:
    python bench/multihop_rag/scripts/run_query_chunk.py --chunk-index 0   # query 0-499
    python bench/multihop_rag/scripts/run_query_chunk.py --chunk-index 1   # query 500-999
    ...
    python bench/multihop_rag/scripts/run_query_chunk.py --chunk-index 5   # query 2500-2555

结果追加写入 v4flash_full_v2/retrieval_results.json（与 MultiHopEvalRunner 的 resume 兼容）。
LLM 调用追加写入 v4flash_full_v2/llm_calls_query.jsonl。
"""

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path

BENCH_ROOT = Path(__file__).parent.parent
PROJECT_ROOT = BENCH_ROOT.parent.parent

if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")

# 从 .env 载入 DEEPSEEK_API_KEY
envf = PROJECT_ROOT / ".env"
if envf.exists():
    for line in envf.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

os.environ["DEEPSEEK_MODEL"] = "deepseek-chat"
os.environ["MCS_NO_SUMMARY_REGEN"] = "1"

# 配置
DB_PATH = BENCH_ROOT / "outputs" / "v4flash_full_v2" / "multihop_v4flash_full.db"
OUTPUT_DIR = BENCH_ROOT / "outputs" / "v4flash_full_v2"
TOKEN_BUDGET = 32000
CHUNK_SIZE = 500

OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(OUTPUT_DIR / "query_chunk.log", encoding="utf-8", mode="a"),
        logging.StreamHandler(),
    ],
)
logging.getLogger("jieba").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)

from bench.multihop_rag.builder import _attach_llm_recorder, _make_mcs
from bench.multihop_rag.data import MultiHopDataLoader, filter_queries
from bench.multihop_rag.metrics import retrieved_docs

# 延迟导入 doc_rerank（bench-only 插件，避免循环依赖）
def _doc_rerank(nodes, query, top_n):
    from bench.plugins.doc_rerank import doc_rerank
    return doc_rerank(nodes, query, top_n=top_n)


def main() -> None:
    parser = argparse.ArgumentParser(description="分块查询评测")
    parser.add_argument(
        "--chunk-index", type=int, required=True, help="块编号 (0-based)"
    )
    parser.add_argument(
        "--chunk-size", type=int, default=CHUNK_SIZE, help="每块 query 数（默认 500）"
    )
    args = parser.parse_args()

    # 加载 queries
    loader = MultiHopDataLoader()
    _, queries = loader.load()
    queries = filter_queries(queries, exclude_null=False)

    total = len(queries)
    start = args.chunk_index * args.chunk_size
    end = min(start + args.chunk_size, total)

    if start >= total:
        print(f"chunk-index={args.chunk_index} 超出范围（共 {total} 个 query），跳过")
        return

    chunk_queries = queries[start:end]
    print("=" * 60)
    print(
        f"分块查询 — chunk {args.chunk_index}: "
        f"query [{start}, {end}) / {total}（共 {len(chunk_queries)} 个）"
    )
    print("=" * 60)

    # 加载已有 MCS 实例（建图幂等跳过，直接用 DB）
    print("加载 MCS 实例（从已有 DB）…")
    mcs = _make_mcs(
        "deepseek",
        str(DB_PATH),
        token_budget=TOKEN_BUDGET,
        record_path=str(OUTPUT_DIR / "llm_calls_query.jsonl"),
        rerank=True,
        rerank_top_n=50,
        rerank_min_score=0.0,
    )

    # 断点续跑：复用已有结果
    results_file = OUTPUT_DIR / "retrieval_results.json"
    results: dict[str, dict] = {}
    if results_file.exists():
        try:
            results = json.loads(results_file.read_text(encoding="utf-8"))
            print(f"已有 {len(results)} 个 query 结果（已完成的会跳过）")
        except Exception:
            print("无法读取已有 retrieval_results.json，从头开始")

    done = set(results)

    def _persist() -> None:
        results_file.write_text(
            json.dumps(results, ensure_ascii=False), encoding="utf-8"
        )

    # 跑查询
    t0 = time.time()
    for i, q in enumerate(chunk_queries, 1):
        if q.query_id in done:
            continue
        try:
            nodes = mcs.query(q.query)
            nodes = nodes if isinstance(nodes, list) else []
        except Exception:
            logging.exception("query 失败: %s", q.query_id)
            nodes = []
        ranked = _doc_rerank(nodes, q.query, top_n=None)
        results[q.query_id] = {
            "type": q.question_type,
            "gold": sorted(q.gold_doc_titles),
            "ranked": ranked,
        }
        if i % 20 == 0 or i == len(chunk_queries):
            print(f"  chunk {args.chunk_index}: query {i}/{len(chunk_queries)}")
        _persist()

    elapsed = time.time() - t0
    print(f"\nchunk {args.chunk_index} 完成！耗时 {elapsed:.0f}s ({elapsed/60:.1f}min)")
    print(f"累计结果: {len(results)} 个 query")

    mcs.shutdown()
    print("已关闭 MCS 实例。")


if __name__ == "__main__":
    main()

"""MultiHop-RAG 成本估算脚本（dry run）。

不调用 LLM，仅估算首建图的 token 消耗和费用。
用于评估预算。
"""

import sys
from pathlib import Path

BENCH_ROOT = Path(__file__).parent.parent

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

# 配置（硬编码）
CORPUS_SUBSET = 200
MAX_CHUNKS = 8

print("=" * 60)
print("MultiHop-RAG Dry Run — 首建图成本估算")
print("=" * 60)

from mcs.bench.multihop_rag import MultiHopEvalConfig, MultiHopEvalRunner

config = MultiHopEvalConfig(
    corpus_subset=CORPUS_SUBSET,
    max_chunks_per_doc=MAX_CHUNKS,
    dry_run=True,
)

runner = MultiHopEvalRunner(config)
estimate = runner.dry_run()

print("\n成本估算完成！")

"""MultiHop-RAG 节点级重排评测脚本。

启用核心 rerank 插件（LexicalScorer），对 query() 返回的节点打词法分重排。
与基线对照，评估节点级重排对文档级指标的影响。
"""

import os
import sys
from pathlib import Path

BENCH_ROOT = Path(__file__).parent.parent
PROJECT_ROOT = BENCH_ROOT.parent.parent

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

envf = PROJECT_ROOT / ".env"
if envf.exists():
    for line in envf.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip())

# 配置（硬编码）
DB_PATH = BENCH_ROOT / "outputs" / "node_rerank" / "multihop_bench.db"
OUTPUT_DIR = BENCH_ROOT / "outputs" / "node_rerank"
CORPUS_SUBSET = 200
K_VALUES = [2, 4, 10]
RERANK_TOP_N = 0  # 0 = 不截断

import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

print("=" * 60)
print("Multihop RAG 节点级重排 — 200 文档, LexicalScorer")
print("=" * 60)

from mcs.bench.multihop_rag import MultiHopEvalConfig, MultiHopEvalRunner

DB_PATH.parent.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

config = MultiHopEvalConfig(
    llm_backend="deepseek",
    corpus_subset=CORPUS_SUBSET,
    db_path=str(DB_PATH),
    output_dir=str(OUTPUT_DIR),
    k_values=K_VALUES,
    resume=True,
    rerank=True,  # 节点级重排
    rerank_top_n=RERANK_TOP_N,
    exclude_null=True,
)

runner = MultiHopEvalRunner(config)
metrics = runner.run()

print("\n节点级重排评测完成！")

"""MultiHop-RAG 文档级重排评测脚本。

启用 bench 专用的文档级重排（doc_rerank），对候选文档直接打词法分排序。
绕过节点→文档映射的稀释/错位。与节点级 rerank 正交。
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
DB_PATH = BENCH_ROOT / "outputs" / "doc_rerank" / "multihop_bench.db"
OUTPUT_DIR = BENCH_ROOT / "outputs" / "doc_rerank"
CORPUS_SUBSET = 200
K_VALUES = [2, 4, 10]
DOC_RERANK_TOP_N = 0  # 0 = 不截断

import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

print("=" * 60)
print("Multihop RAG 文档级重排 — 200 文档, doc_rerank")
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
    rerank=False,  # 文档级重排不依赖节点级
    doc_rerank=True,  # 启用文档级重排
    doc_rerank_top_n=DOC_RERANK_TOP_N,
    exclude_null=True,
)

runner = MultiHopEvalRunner(config)
metrics = runner.run()

print("\n文档级重排评测完成！")

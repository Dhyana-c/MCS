"""MultiHop-RAG 基线评测脚本。

切块摄入（默认 max_chunks=8），不启用节点级/文档级重排。
用于建立基线对照。
"""

import os
import sys
from pathlib import Path

BENCH_ROOT = Path(__file__).parent.parent
PROJECT_ROOT = BENCH_ROOT.parent.parent

# 直接运行脚本时 sys.path[0] 是脚本目录而非项目根；加入项目根以便 import bench.*
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

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
DB_PATH = BENCH_ROOT / "outputs" / "baseline" / "multihop_bench.db"
OUTPUT_DIR = BENCH_ROOT / "outputs" / "baseline"
CORPUS_SUBSET = 200
K_VALUES = [2, 4, 10]
MAX_CHUNKS = 8

import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

print("=" * 60)
print("Multihop RAG 基线 — 200 文档, 切块摄入, 无重排")
print("=" * 60)

from bench.multihop_rag import MultiHopEvalConfig, MultiHopEvalRunner

DB_PATH.parent.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

config = MultiHopEvalConfig(
    llm_backend="deepseek",
    corpus_subset=CORPUS_SUBSET,
    db_path=str(DB_PATH),
    output_dir=str(OUTPUT_DIR),
    k_values=K_VALUES,
    max_chunks_per_doc=MAX_CHUNKS,
    resume=True,
    rerank=False,  # 基线：不重排
)

runner = MultiHopEvalRunner(config)
metrics = runner.run()

print("\n基线评测完成！")
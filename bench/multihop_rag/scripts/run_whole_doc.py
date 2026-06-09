"""MultiHop-RAG 整篇文档摄入评测脚本。

整篇模式（标题+正文作为单个单元）+ 篇内关系边修复（judge 输出 edges_to_names）。
可断点续跑。独立库/输出。使用 deepseek-chat 后端。
"""

import os
import sys
from pathlib import Path

# bench/multihop_rag/
BENCH_ROOT = Path(__file__).parent.parent
PROJECT_ROOT = BENCH_ROOT.parent.parent

# 直接运行脚本时 sys.path[0] 是脚本目录而非项目根；加入项目根以便 import bench.*
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

if sys.platform == "win32":
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stderr.reconfigure(encoding="utf-8")

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

# 配置（硬编码）
DB_PATH = BENCH_ROOT / "outputs" / "whole_doc" / "multihop_chat_200_v2.db"
OUTPUT_DIR = BENCH_ROOT / "outputs" / "whole_doc"
CORPUS_SUBSET = 200
K_VALUES = [2, 4, 10]

import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(OUTPUT_DIR / "decisions.log", encoding="utf-8"),
        logging.StreamHandler(),
    ],
)
logging.getLogger("jieba").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)

print("=" * 60)
print("Multihop RAG (DeepSeek-chat) — 200 文档, 整篇摄入")
print("=" * 60)

from bench.multihop_rag import MultiHopEvalConfig, MultiHopEvalRunner

DB_PATH.parent.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

config = MultiHopEvalConfig(
    llm_backend="deepseek",
    corpus_subset=CORPUS_SUBSET,
    whole_doc=True,
    db_path=str(DB_PATH),
    output_dir=str(OUTPUT_DIR),
    k_values=K_VALUES,
    resume=True,
)

runner = MultiHopEvalRunner(config)
metrics = runner.run()

print("\n评估完成！")

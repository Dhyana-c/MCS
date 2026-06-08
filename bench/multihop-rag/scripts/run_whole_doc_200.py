"""MultiHop-RAG 整篇文档摄入评测脚本（200 文档全量）。

整篇模式（标题+正文作为单个单元）+ SQLite 持久化 + 断点续跑。模型：deepseek-v4-flash。
与 run_whole_doc_20.py 同配置，仅语料规模放大到 200。独立 db / 输出目录，完整记录
（decisions.log / llm_calls.jsonl / retrieval_results.json / metrics.json）。
"""

import os
import sys
from pathlib import Path

# 脚本所在目录的父目录（bench/multihop-rag/）
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

# 模型显式锁定 deepseek-v4-flash（与 20 篇验证一致）
os.environ["DEEPSEEK_MODEL"] = "deepseek-v4-flash"
# 文档级检索不依赖逐节点摘要文本，关掉省 ~2.6× LLM 调用（与 20 篇脚本一致）
os.environ["MCS_NO_SUMMARY_REGEN"] = "1"

# 配置（硬编码）
DB_PATH = BENCH_ROOT / "outputs" / "whole_doc_200" / "multihop_200.db"
OUTPUT_DIR = BENCH_ROOT / "outputs" / "whole_doc_200"
CORPUS_SUBSET = 200
K_VALUES = [2, 4, 10]

import logging

# 先建目录，再装 FileHandler（否则 basicConfig 打开日志文件会 FileNotFoundError）
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

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
print("Multihop RAG (deepseek-v4-flash) — 200 文档全量, 整篇摄入")
print("=" * 60)

from bench.multihop_rag import MultiHopEvalConfig, MultiHopEvalRunner

config = MultiHopEvalConfig(
    llm_backend="deepseek",
    corpus_subset=CORPUS_SUBSET,
    whole_doc=True,
    db_path=str(DB_PATH),
    output_dir=str(OUTPUT_DIR),
    k_values=K_VALUES,
    resume=True,  # 断点续跑：已摄入文档跳过 + 已评 query 跳过
)

runner = MultiHopEvalRunner(config)
metrics = runner.run()

print("\n评估完成！")

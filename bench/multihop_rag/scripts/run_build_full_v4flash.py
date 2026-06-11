"""全量 609 篇文档建图脚本（deepseek-chat, token_budget=32000, 单向边模型）。

只建图不查询，支持断点续跑。使用 .env 中的 DEEPSEEK_API_KEY。
"""

import os
import sys
import time
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

# 模型改为 deepseek-chat（更快、限速更宽松）
os.environ["DEEPSEEK_MODEL"] = "deepseek-chat"
os.environ["MCS_NO_SUMMARY_REGEN"] = "1"

# 配置
DB_PATH = BENCH_ROOT / "outputs" / "full_32k" / "multihop_full.db"
OUTPUT_DIR = BENCH_ROOT / "outputs" / "full_32k"
TOKEN_BUDGET = 32000

DB_PATH.parent.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    handlers=[
        logging.FileHandler(OUTPUT_DIR / "build.log", encoding="utf-8", mode="a"),
        logging.StreamHandler(),
    ],
)
logging.getLogger("jieba").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)

print("=" * 60)
print("全量建图 (deepseek-chat) — 609 文档, token_budget=32000, 单向边模型")
print("=" * 60)

from bench.multihop_rag.builder import build_shared_graph
from bench.multihop_rag.data import MultiHopDataLoader

DB_PATH.parent.mkdir(parents=True, exist_ok=True)
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

loader = MultiHopDataLoader()
docs, _ = loader.load()  # 不需要 queries，只建图

print(f"加载 {len(docs)} 篇文档，开始建图…")
t0 = time.time()

mcs = build_shared_graph(
    docs,
    llm="deepseek",
    db_path=str(DB_PATH),
    whole_doc=True,
    token_budget=TOKEN_BUDGET,
    record_path=str(OUTPUT_DIR / "llm_calls.jsonl"),
)

elapsed = time.time() - t0
print(f"\n建图完成！耗时 {elapsed:.0f}s ({elapsed/60:.1f}min)")

# 输出图统计
store = mcs.store
nodes = store.get_all_nodes()
edges = store.get_all_edges()
print(f"节点数: {len(nodes)}, 边数: {len(edges)}")

# 角色 + 不变量快检
from mcs.core.token_budget import TokenBudget
from mcs.plugins.maintenance.fanout_reducer import SEED_ROOT_ID

roles = {}
for n in nodes:
    roles[n.role] = roles.get(n.role, 0) + 1
print(f"角色分布: {roles}")

root = store.get_node(SEED_ROOT_ID)
if root:
    root_children = store.get_neighbors(SEED_ROOT_ID)
    print(f"root 直连子节点: {len(root_children)}")

tb = TokenBudget(TOKEN_BUDGET)
violations = 0
for n in nodes:
    neighbors = store.get_neighbors(n.id)
    total = tb.estimate_node(n)
    for nb in neighbors:
        total += tb.estimate_node(nb)
    if total > tb.T:
        violations += 1
print(f"不变量违反节点数: {violations}")

mcs.shutdown()
print("已关闭 MCS 实例。")

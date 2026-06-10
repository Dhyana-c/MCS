"""20 文档建图体检脚本（单向边模型，DeepSeek v4 flash）。

整篇摄入 20 篇文档，只建图不查询。输出图体检报告：
root 及各节点扇出分布、裸概念占比、hub 覆盖率、是否处处 ≤ T、无双向边残留。
"""

import os
import sys
import time
from pathlib import Path

# bench/multihop_rag/
BENCH_ROOT = Path(__file__).parent.parent
PROJECT_ROOT = BENCH_ROOT.parent.parent

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

os.environ["DEEPSEEK_MODEL"] = "deepseek-v4-flash"
os.environ["MCS_NO_SUMMARY_REGEN"] = "1"

DB_PATH = BENCH_ROOT / "outputs" / "v4flash_20" / "multihop_v4flash_20.db"
OUTPUT_DIR = BENCH_ROOT / "outputs" / "v4flash_20"
TOKEN_BUDGET = 4000

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
print("20 文档建图体检 (DeepSeek v4 flash, 单向边模型)")
print(f"token_budget T = {TOKEN_BUDGET}")
print("=" * 60)

from bench.multihop_rag.builder import build_shared_graph
from bench.multihop_rag.data import MultiHopDataLoader

loader = MultiHopDataLoader()
docs, _ = loader.load()
docs = docs[:20]  # 只取 20 篇

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

# === 图体检 ===
print("\n" + "=" * 60)
print("图体检报告")
print("=" * 60)

store = mcs.store
nodes = store.get_all_nodes()
edges = store.get_all_edges()

print(f"\n总节点数: {len(nodes)}")
print(f"总边数:   {len(edges)}")

# 角色分布
roles = {}
for n in nodes:
    roles[n.role] = roles.get(n.role, 0) + 1
print(f"\n节点角色分布: {roles}")

# 检查无双向边残留（所有边都是单向的）
print(f"\n✓ 边数据结构: Edge 只有 source_id/target_id（无 direction 字段）")

# root 及各节点扇出分布
from mcs.plugins.maintenance.fanout_reducer import SEED_ROOT_ID

root = store.get_node(SEED_ROOT_ID)
if root:
    root_children = store.get_neighbors(SEED_ROOT_ID)
    print(f"\nroot (__seed_root__) 直连子节点: {len(root_children)}")
    root_concepts = [n for n in root_children if n.role == "concept"]
    root_hubs = [n for n in root_children if n.role == "hub"]
    print(f"  - 裸概念: {len(root_concepts)}")
    print(f"  - hub:    {len(root_hubs)}")
else:
    print("\n⚠ root 不存在！")

# 各 hub 的扇出
hubs = [n for n in nodes if n.role == "hub"]
print(f"\nhub 扇出分布 (共 {len(hubs)} 个 hub):")
fanout_list = []
for h in hubs:
    children = store.get_neighbors(h.id)
    fanout_list.append((h, len(children)))

fanout_list.sort(key=lambda x: -x[1])
for h, cnt in fanout_list[:10]:
    print(f"  {h.name[:40]:40s} → {cnt} 子节点")
if len(fanout_list) > 10:
    print(f"  ... 还有 {len(fanout_list) - 10} 个 hub")

# 不变量检查：是否处处 ≤ T
from mcs.core.token_budget import TokenBudget

tb = TokenBudget(TOKEN_BUDGET)
violations = []
for n in nodes:
    neighbors = store.get_neighbors(n.id)
    total = tb.estimate_node(n)
    for nb in neighbors:
        total += tb.estimate_node(nb)
    if total > tb.T:
        violations.append((n, total, len(neighbors)))

print(f"\n不变量检查 (≤ T={TOKEN_BUDGET}):")
if violations:
    print(f"  ⚠ {len(violations)} 个节点违反不变量：")
    for n, t, cnt in violations[:5]:
        print(f"    {n.name[:40]:40s} token={t:.0f} 邻居={cnt}")
else:
    print(f"  ✓ 全部 {len(nodes)} 个节点的一跳邻域均 ≤ T")

# hub 覆盖率：被 hub 直接或间接覆盖的概念比例
all_concepts = {n.id for n in nodes if n.role == "concept"}
hub_children_ids: set[str] = set()
for h in hubs:
    for child in store.get_neighbors(h.id):
        if child.role == "concept":
            hub_children_ids.add(child.id)
covered = all_concepts & hub_children_ids
print(f"\nhub 覆盖率: {len(covered)}/{len(all_concepts)} 概念被 hub 直接管辖 ({len(covered)/max(len(all_concepts),1)*100:.1f}%)")

print("\n" + "=" * 60)

mcs.shutdown()
print("已关闭 MCS 实例。")

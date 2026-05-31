"""One-item connectivity smoke test (real DeepSeek). Surfaces auth/model errors."""
import os
from pathlib import Path

# load .env into environment
for line in Path(r"D:\code\mcs\.env").read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        os.environ[k.strip()] = v.strip()
print("key prefix:", os.environ.get("DEEPSEEK_API_KEY", "")[:6] + "...")

from mcs.bench.hotpot import HotpotItem, extract_prediction, ingest_hotpot_item

item = HotpotItem(
    _id="smoke",
    question="What nationality is the director of the film Ed Wood?",
    answer="American",
    supporting_facts=[["Ed Wood", 0]],
    context=[
        ["Ed Wood", ["Ed Wood is a 1994 American film directed by Tim Burton."]],
        ["Tim Burton", ["Tim Burton is an American film director."]],
    ],
    type="bridge",
    level="hard",
)

mcs = ingest_hotpot_item(item, llm="deepseek")
nodes = mcs.query(item.question)
nodes = nodes if isinstance(nodes, list) else []
print("node count:", len(nodes))
print("prediction:", extract_prediction(nodes, "smoke", item.question))
mcs.shutdown()
print("SMOKE OK")

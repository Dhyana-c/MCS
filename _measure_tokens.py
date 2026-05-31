"""Measure REAL per-item token usage (instruments the OpenAI client)."""
import json
import os
from pathlib import Path

for line in Path(r"D:\code\mcs\.env").read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        os.environ[k.strip()] = v.strip()

from openai.resources.chat.completions import Completions

_orig = Completions.create
AGG = {"prompt": 0, "completion": 0, "hit": 0, "miss": 0, "calls": 0}
_seen = {"done": False}


def _wrapped(self, *args, **kwargs):
    resp = _orig(self, *args, **kwargs)
    u = getattr(resp, "usage", None)
    if u is not None:
        d = u.model_dump() if hasattr(u, "model_dump") else dict(u)
        if not _seen["done"]:
            print("USAGE FIELDS:", json.dumps(d))
            _seen["done"] = True
        AGG["prompt"] += d.get("prompt_tokens", 0) or 0
        AGG["completion"] += d.get("completion_tokens", 0) or 0
        AGG["hit"] += d.get("prompt_cache_hit_tokens", 0) or 0
        AGG["miss"] += d.get("prompt_cache_miss_tokens", 0) or 0
        AGG["calls"] += 1
    return resp


Completions.create = _wrapped

from mcs.bench.hotpot import HotpotDataLoader, ingest_hotpot_item

items = HotpotDataLoader(
    r"D:\code\hotpot\hotpot_dev_distractor_v1.json",
    subset=2, sample_strategy="uniform", seed=7,
).load()

rows = []
for it in items:
    b = dict(AGG)
    try:
        mcs = ingest_hotpot_item(it, llm="deepseek")
        mcs.query(it.question)
        mcs.shutdown()
    except Exception as e:
        print("item error:", it._id, repr(e))
    pin = AGG["prompt"] - b["prompt"]
    pout = AGG["completion"] - b["completion"]
    pcalls = AGG["calls"] - b["calls"]
    print(f"ITEM {it._id} type={it.type} calls={pcalls} "
          f"prompt={pin} completion={pout} total={pin + pout}")
    rows.append((pcalls, pin, pout))

n = len(rows) or 1
print("=== AVG PER ITEM ===")
print("calls=%.1f prompt=%.0f completion=%.0f total=%.0f" % (
    sum(r[0] for r in rows) / n,
    sum(r[1] for r in rows) / n,
    sum(r[2] for r in rows) / n,
    sum(r[1] + r[2] for r in rows) / n,
))
print("TOTAL prompt=%d completion=%d cache_hit=%d cache_miss=%d calls=%d" % (
    AGG["prompt"], AGG["completion"], AGG["hit"], AGG["miss"], AGG["calls"]))

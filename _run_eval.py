"""Run a real 10-case HotpotQA eval (loads key from .env)."""
import os
from pathlib import Path

for line in Path(r"D:\code\mcs\.env").read_text(encoding="utf-8").splitlines():
    line = line.strip()
    if line and not line.startswith("#") and "=" in line:
        k, v = line.split("=", 1)
        os.environ[k.strip()] = v.strip()

from mcs.bench.hotpot import HotpotEvalConfig, HotpotEvalRunner

cfg = HotpotEvalConfig(subset=10, output_dir="./bench_output", resume=False)
runner = HotpotEvalRunner(cfg)
metrics = runner.run()
print("FINAL METRICS:", metrics)

# HotpotQA 多跳问答评测

占位目录。HotpotQA 评测功能已实装在 `mcs.bench.hotpot` 模块中。

## 现有功能

参见 `mcs/bench/README.md` 和 `mcs/bench/hotpot.py`。

## 使用方式

```python
from mcs.bench import HotpotEvalRunner, HotpotEvalConfig

config = HotpotEvalConfig(
    subset=100,
    llm_backend="deepseek",
    output_dir="./bench_output",
)

runner = HotpotEvalRunner(config)
metrics = runner.run()
```

## 后续迁移

计划将 HotpotQA 的启动脚本迁移到本目录，与 MultiHop-RAG 保持一致的组织结构。

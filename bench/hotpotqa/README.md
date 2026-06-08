# HotpotQA 多跳问答评测

HotpotQA 评测代码位于本目录 `runner.py`，可作为库导入，也可经 `python -m bench.hotpotqa` 运行。

## 使用方式

CLI（从项目根目录运行）：

```bash
# 估算 token 消耗（不调用 LLM）
python -m bench.hotpotqa --dry-run --subset 100

# 正式评测（100 条子集，DeepSeek 后端）
python -m bench.hotpotqa --subset 100 --output ./bench_output
```

作为库导入：

```python
from bench.hotpotqa import HotpotEvalRunner, HotpotEvalConfig

config = HotpotEvalConfig(
    subset=100,
    llm_backend="deepseek",
    output_dir="./bench_output",
)

runner = HotpotEvalRunner(config)
metrics = runner.run()
```

API key 从环境变量 `DEEPSEEK_API_KEY`（或 `ANTHROPIC_API_KEY`）读取。

## 后续

计划在 `bench/hotpotqa/scripts/` 下补充无参启动脚本，与 MultiHop-RAG 保持一致的组织结构。

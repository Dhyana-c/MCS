# 已知问题

> 本文档仅记录未修复的开放问题。已修复项已清理，历史见 git log。

## MCS Core

### LLM 瞬时错误处理

429 / 网络抖动目前直接吞成空结果（计为 miss）。需加重试 + 退避（并发时尤其必要）。

- **涉及**：`mcs/interfaces/llm.py`、LLM 适配器

### `_locate_seeds` 单 entry 插件容错

目前任一 EntryPlugin 的 `locate` 抛异常会拖垮整个种子定位。navigate_hub 宽容后已大幅缓解，但仍建议 `_locate_seeds` 对单插件异常 try/except 降级。

- **涉及**：`mcs/core/query_engine.py:_locate_seeds`

## 评测

### query 阶段并发

query 是只读、彼此独立 → `ThreadPoolExecutor` 加速，配合重试/退避。build 是写共享图、必须串行，无法并发。

## 收尾

### 归档完成的 change

`multihop-rag-eval` 等 change 需归档（`openspec archive ...`）。

### 清理临时脚本

`_smoke_test.py`、`_run_eval.py`、`_measure_tokens.py` 及根目录 `*.log`、`_measure_tokens/`、`bench_output*` 等评测产物。

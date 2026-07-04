# 已知问题

> 本文档仅记录未修复的开放问题。已修复项已清理，历史见 git log。

## MCS Core

### 写路径同名索引全图扫描

`_apply_decisions` 每次 ingest 用 `get_all_nodes()` 全图扫描重建 `existing_by_name`（O(N)/次）；
批量整合碎片时为 O(F×N)。图增长后是写路径主要冷开销，宜维护持久 name→id 索引。

- **涉及**：`mcs/core/write_pipeline.py:_apply_decisions`

### alias 索引更新与种子噪音

`AliasIndexPlugin.remove_entry` 线性扫全索引（每个 changed 节点一次）；且词条全部 jieba
子词入索（含高频单字），常见字查询命中海量种子后仅按到达顺序截断，种子质量随图增长退化。

- **涉及**：`mcs/plugins/index/alias_index.py`

## 评测

### query 阶段并发

query 是只读、彼此独立 → `ThreadPoolExecutor` 加速，配合重试/退避。build 是写共享图、必须串行，无法并发。

## 收尾

### 归档完成的 change

`multihop-rag-eval` 等 change 需归档（`openspec archive ...`）。

### 清理临时脚本

`_smoke_test.py`、`_run_eval.py`、`_measure_tokens.py` 及根目录 `*.log`、`_measure_tokens/`、`bench_output*` 等评测产物。

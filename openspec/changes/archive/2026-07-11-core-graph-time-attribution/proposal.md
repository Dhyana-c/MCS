## Why

日记场景暴露：`extract_concepts` 允许日期进概念/事实 content，导致 ① 概念带单次时间（按摩 content="计划今晚进行"）、② 事件性命题被抽成概念（"未去按摩的情况"自述是事件却进了核心图）、③ 同名概念 content 拼接损坏（按摩两条直接拼）。核心图被带时间、不可复用、互相冲突的伪节点污染。「概念/事实是稳定核心图、事件带时间」本是宪法双层的自然推论，但抽取 prompt 与 merge 逻辑都没守这个规矩（③ 经查是 spec 规定的「追加」行为，非 bug —— 本变更是 spec 行为变更）。

## What Changes

- **确立三类节点时间归属不变量**（按节点类型分）：**概念 content 零时间**（纯名词定义，不含任何时间）；**事实 content 禁相对/单次时间、允许固定历史时间**（命题属性，如"创立于 1976"）；事件带 timestamp。相对/单次时间词（今天/这次/未完成/计划中）禁进概念/事实 content。
- **`extract_concepts` prompt 守时间归属**：概念 content 零时间；事实 content 禁相对时间词、允许固定历史时间；带时间的发生 → 去时间化作事实（时间归事件层）；不抽事件性/偏好性命题（"未去按摩的情况"归事件层）；不归纳偏好/模式（"喜欢按摩"不抽，靠 degree 涌现）。
- **merge content 从「追加」改「语义合并」**（方案 b，**三路径统一**）：抽公共 `merge_content` helper，统一 3 条字面合并路径——write path `_dispatch_merge` 改 LLM 语义合并、读路径 `_try_read_repair` + 后台 `dedup_maintenance` 改"子串才合、非子串不合（保留节点）"（零 LLM、不丢不拼）；**协调 `merge-content-compaction`**：压缩段保留，前提从「追加后超阈值」改「合并后超阈值」。（根因：3 处同款换行追加 —— `_dispatch_merge:565` / `query_engine:388` / `dedup_maintenance:121`，非 bug 是 spec 规定的追加行为，本变更为 spec + 代码统一变更。）
- **清损坏数据**：`mcs_mem` db（mcs.db）已损坏的概念/事实 content 清理。

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

- `unified-graph-schema`：三类节点时间归属不变量（概念 content 零时间、事实禁相对/单次时间允许固定历史时间、事件带 timestamp）+ **图质量最终收敛 content 合并守则**（公共 `merge_content` helper、不机械追加、read-repair/dedup 零 LLM 子串才合非子串保留、write path LLM 语义合并）。
- `write-pipeline`：`extract_concepts` prompt 守时间归属 + merge content 从追加改语义合并（RENAME + MODIFY「merge 时 concept content 追加到目标节点」→「语义合并到目标节点」）。
- `merge-content-compaction`：压缩触发前提从「追加后」改「合并后」（MODIFY）。

## Impact

- **`mcs/prompts/extract_concepts.py`**：prompt 加时间归属约束（概念零时间、事实禁相对时间允许固定历史、去时间化事实、不抽事件性/偏好性）；删除行 27「日期」鼓励。
- **`mcs/core/` 新 helper**：`merge_content(target, incoming, merge_llm=None) -> str` 公共函数 + 新 LLM 语义合并 purpose（与 `merge.py` 措辞对齐；purpose 模板携带 `node_class` 按节点类型分流时间归属——概念零时间、事实保留固定历史时间）。
- **`mcs/core/write_pipeline.py` `_dispatch_merge`**（行 545-589，write path ⑤ 应用决策 + `_merge_concept_into` 同名去重）：改用 helper（传 merge_llm）。
- **`mcs/core/query_engine.py` `_try_read_repair`**（行 386-392，query 读路径）：改用 helper（**不传 merge_llm** → 非子串不碰、被并方节点保留）；读路径零 LLM。
- **`mcs/plugins/maintenance/dedup_maintenance.py`**（行 119-141，后台扫描，当前未接入运行）：改用 helper（**不传 merge_llm** → 子串才合删 dup、非子串保留 dup 不合）+ docstring；保留重挂边 / 互斥禁合 / 超 T 挂起。彻底合并靠 write path。
- **`openspec/specs/merge-content-compaction/spec.md`**：压缩前提协调（追加后 → 合并后）。
- **`mcs_mem` db（mcs.db）**：损坏的概念/事实 content 清理（重抽 or 抹掉）。
- **不归纳偏好/模式**（Phase 2 再考虑归纳管线）。
- **归属**：#1/#2/#3 主体在 mcs-core（时间归属是统一模型双层落实 = 通用不变量）；#4 清数据在 mcs_mem。不在 mem 层搞覆写 prompt 的特化机制。

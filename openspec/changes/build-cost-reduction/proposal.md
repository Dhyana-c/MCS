## Why

建图（ingest）是 MCS 总花费的大头——本次 MultiHop-RAG 评测的 ¥110 主要烧在 200 篇 build 上。代码确认的成本根源：
- **阶段②"关联节点定位"复用了完整的多轮 LLM 查询循环**（`write_pipeline.py:113` 调 `query_engine.query`，最多 5 轮、每轮 `decide_directions`）——**每摄入一个块就跑一次完整 LLM 查询**，1599 块=1599 次，且图越大越贵（super-linear）。
- **压缩判定每块都触发**（阶段⑥ fanout_reducer/summary_regen）。
- **DeepSeek 前缀缓存命中仅 ~3%**（prompt 可缓存前缀太小）。

本 change 以"**先量化、再优化、且不劣化图质量**"为纪律，系统性降低建图 token 成本。

## What Changes

- **建图成本 instrumentation + 真实 dry-run 模型**（concrete 硬交付）：按 purpose/阶段统计实际 token 与调用数；修正 dry-run（含 super-linear 建图 + query 阶段），跑前可预见、跑时可实时盯+设上限
- **阶段②轻量化锚点定位**（最大单一杠杆）：把"找锚点"从完整 LLM 查询循环换成轻量检索（alias_index / 嵌入相似度）；预期既省钱又可能召回更好；以成本+连通性诊断双重验证、**不得劣化图质量**
- **批量 build 压缩延后**：bulk 摄入时压缩改为最后统一跑一次（deferred/batch compaction 模式）
- **prompt 结构对齐前缀缓存**：固定内容前置、可变材料后置，最大化可缓存前缀（命中走约 1/10 价）
- **（探索）judge_relations 嵌入预筛**：嵌入相似度先筛，LLM 只裁决模糊对
- 便宜杠杆：off-peak 调度建议、更粗分块 knob

## Capabilities

### New Capabilities
- `build-cost-reduction`: 建图阶段的成本度量与优化——以"成本 instrumentation + 真实预估"为硬约束；各项优化以"经度量证明净省 token 且不劣化连通性诊断"才纳入的软要求表达

### Modified Capabilities

（本 change 暂不硬 commit 对 `write-pipeline` 阶段②/压缩时机的 spec 级行为变更——探索阶段先用开关+实验、留 Open Questions；定型后再补 Modified delta）

## Impact

- 改 `mcs/core/write_pipeline.py`（阶段②锚点定位、压缩时机），可能新增嵌入依赖（本地 sentence-transformer 或 API）
- **协调**：与 `graph-construction-quality` 共用阶段②代码——那个管"连通性/质量"，本 change 管"成本"；阶段②轻量化须**同时**满足省钱与不劣化连通性（复用其图质量诊断作硬护栏）
- 依赖 `query-rerank-and-persistence` 的序列化修复，才能在已落盘图上做成本/质量对照
- **风险**：阶段②换轻量检索若做不好会降低锚点质量→图更碎（与 graph-construction-quality 冲突）→ 连通性诊断是硬护栏
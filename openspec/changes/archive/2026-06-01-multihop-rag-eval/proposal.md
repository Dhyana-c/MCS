## Why

HotpotQA 评测暴露了 MCS 与该 benchmark 的范式错配：HotpotQA-distractor 每条数据独立、上下文只有 10 段、用完即弃、推理只有 2 跳——为适配它，MCS 不得不关掉自己最核心的能力（共享、可积累的大图），实测还要 ~90K token/条去建一张一次性图。我们需要一个真正落在 MCS Phase-1 能力区间内的"扬长"评测：共享语料一次建图、跨文档多跳检索、事实静态一致（不依赖尚未实现的矛盾仲裁/时序淘汰）。MultiHop-RAG 正好满足这些条件。

## What Changes

- 新增 `mcs/bench/multihop_rag.py` 模块：MultiHop-RAG 端到端检索评测框架
- 新增数据加载器：读取 MultiHop-RAG 的 `corpus.json`（新闻文档）与 `MultiHopRAG.json`（query + evidence_list）
- 新增**共享图**构建器：把整个语料逐篇 `ingest()` 进**同一个持久化 MCS 实例**（SQLite，非 `:memory:`），build-once
- 新增查询→证据适配器：对每个 query 调 `mcs.query()`，把返回 `List[Node]` 经 `source_tracking` 映射回来源文档，与 gold `evidence_list` 比对
- 新增检索指标：Hit@k / MAP@k / MRR@k（主），`null_query` 拒答率（抗干扰诊断）
- 新增两层断点续跑：语料 ingest 按 doc_id 跳过（复用 idempotency）；query 按 query_id 进度文件跳过；resume 复用已落盘的图
- 新增 dry-run 成本预估（用实测 ~9K token/段 的真实模型）
- 新增数据获取说明（数据集本地缺失，需从 HuggingFace `yixuantt/MultiHop-RAG` 下载）

## Capabilities

### New Capabilities
- `multihop-rag-eval`: MultiHop-RAG 共享语料多跳检索评测框架，涵盖数据加载、共享图 ingest、查询→证据映射、Hit@k/MAP@k/MRR@k 指标与断点续跑

### Modified Capabilities

（无——不改动任何现有 spec'd 契约；评测是核心代码的外部消费者）

## Impact

- 新增 `mcs/bench/multihop_rag.py`（不影响现有核心代码与 `mcs/bench/hotpot.py`）
- **新增数据依赖**：MultiHop-RAG 数据集本地尚未存在，需下载 `corpus.json` + `MultiHopRAG.json`（约 600 篇文档 / ~2500 query）
- 复用现有 Phase-1 能力：共享图、source_tracking、多跳语义游走；**不需要** Phase-2 的矛盾仲裁/时序淘汰/版本
- 与 hotpot bench 架构相反：共享持久图（build-once、query-many），而非每条独立实例——`load-on-startup` 在此是"复用已建图"的特性而非污染源
- 每次首建图会产生一次性较大 LLM 费用（语料 ingest），之后 query 复用该图、成本低
- 主指标为检索召回（Hit@k），刻意绕开"MCS 不是答题器"的弱点；answer 合成留作后续增强
## Why

已归档的 query-rerank-and-persistence 实装了**节点级**重排：实测把 gold 节点显著往前排（mrr/map 提升 4-5×），但传导到**文档级**指标只到 recall@10 **0.226**——远低于候选集召回 86%、更远低于离线 POC 的 **0.81**。瓶颈是「节点级排序 → 节点→文档映射」这层的**稀释/错位**：文档名次由它第一次出现的节点决定，而那个节点未必是该文档最相关的代表。需要在**评测侧**直接对候选文档打分排序，量化文档级重排的真实收益、把 recall@10 往 POC 推。

## What Changes

- 新增 **bench 专用的文档级重排层**（放 `mcs/bench/` 下，**不进核心 query 插件链、不改 mcs 核心**）：
  - 把 `query()` 召回的 `List[Node]` 按 `source_tracking` 反向聚合成「候选文档 → 该文档下节点文本」的映射；
  - 对每篇候选文档构造**文档级文本**（文档标题/`doc_id` + 该文档下各节点的 `name`/`content`/statements 聚合），用查询直接打**词法**相关性分；
  - 按分降序重排候选文档、截断 top-N，作为最终 `retrieved_docs`。
- `mcs/bench/multihop_rag.py` 加开关 **`--doc-rerank`**（与现有节点级 `--rerank` 正交，可单独启用或对比）。
- 打分**复用词法思路**（token 重叠、name/标题加权，零额外 LLM 调用），便于和节点级 reranker 同口径对比。
- **默认 opt-in**：不启用时评测行为与现状一致。

## Capabilities

### New Capabilities
- `bench-doc-rerank`: 评测专用的**文档级重排**——对 `query()` 召回映射出的候选文档，按「文档级文本与查询的相关性」直接打分、过滤、排序、截断，绕过节点→文档映射的稀释，量化文档级检索收益。打分器与节点级共享词法思路、零额外 LLM 调用，默认 opt-in。

### Modified Capabilities
<!-- 无：本 change 不改既有 capability 的 spec-level 契约。multihop-rag-eval 仅新增一个 opt-in 开关，属本新能力的集成点，不改其既有 requirements。 -->

## Impact

- 新增 `mcs/bench/` 下的文档级重排模块（如 `mcs/bench/doc_rerank.py`）。
- 改 `mcs/bench/multihop_rag.py`：加 `--doc-rerank` 开关 + 在 `retrieved_docs` 处接入文档级重排（不启用时旁路）。
- **不改 mcs 核心**（`mcs/core`、`mcs/plugins`、`mcs/interfaces` 均不动）；与核心节点级 reranker 互不影响。
- 复用 `mcs/plugins/phase1/rerank.py` 的词法 tokenize 思路（按需抽取共享的 token 重叠工具，避免重复实现）。
- 验证近乎零成本：复用已建图 + 已落盘的 `retrieval_results`（节点级），文档级重排作用于同一候选集，直接对比 节点级 vs 文档级 的 Hit@k/MAP/MRR。
- 不改 LLM 调用次数（词法打分零额外调用）。

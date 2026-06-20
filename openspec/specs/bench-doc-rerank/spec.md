## Purpose
提供文档级重排能力，将节点按来源文档聚合后按查询相关性重排，并集成到多跳评测作为 opt-in 开关。

## Requirements

### Requirement: 文档级重排候选文档

The bench layer SHALL provide a document-level reranker that, given the `query()` result `List[Node]` and the query text, maps nodes to their source documents, scores each candidate document by query relevance over document-level text, and returns the documents reranked and truncated by score.

#### Scenario: 按文档级相关性重排

- **WHEN** 评测启用文档级重排，且 `query()` 召回一组 `List[Node]`
- **THEN** 框架 MUST 把节点按 `source_tracking` 的 `doc_id` 反向聚合成候选文档集，对每篇文档用查询文本打相关性分，并 MUST 按分降序返回重排后的文档 id 列表（替代原 `retrieved_docs` 的节点-rank 顺序）

#### Scenario: 文档级文本由标题与召回节点聚合

- **WHEN** 为某候选文档构造打分文本
- **THEN** 文本 MUST 至少包含该文档的 `doc_id`（标题）与该文档下本次被召回节点的 `name`/`content`（及 statements，若有）的聚合；标题 MUST 参与打分

#### Scenario: 过滤低相关并截断 top-N

- **WHEN** 候选文档数超过配置的 top-N，或部分文档相关性低于阈值
- **THEN** 框架 MUST 丢弃低于阈值的文档并截断到 top-N；默认配置 MUST 保守（以排序为主、宽松截断）

#### Scenario: 词法打分且零额外 LLM 调用

- **WHEN** 检查文档级打分
- **THEN** 框架 MUST 至少实装一个**词法**打分（查询与文档级文本的 token 重叠、标题加权），且 MUST NOT 发起额外 LLM 调用；接口 SHOULD 允许后续替换为嵌入/LLM 打分

#### Scenario: 空召回透传

- **WHEN** `query()` 结果为空，或无任何带 `doc_id` 的来源
- **THEN** 框架 MUST 返回空文档列表，不报错

---

### Requirement: 多跳评测集成文档级重排开关

The MultiHop-RAG bench SHALL expose an opt-in switch that routes `retrieved_docs` through the document-level reranker, orthogonal to the node-level `--rerank`.

#### Scenario: 启用文档级重排

- **WHEN** 评测以 `--doc-rerank` 运行
- **THEN** 框架 MUST 对每个 query 用文档级重排产出 `retrieved_docs`，再按现有口径计算 Hit@k/MAP/MRR

#### Scenario: 默认 opt-in 不改基线

- **WHEN** 未传 `--doc-rerank`
- **THEN** `retrieved_docs` MUST 与现状一致（按节点 rank 映射、去重），评测基线不变

#### Scenario: 与节点级重排正交

- **WHEN** 分别或同时启用 `--rerank`（节点级）与 `--doc-rerank`（文档级）
- **THEN** 两者 MUST 可独立组合；文档级重排 MUST 作用于 `query()` 召回节点映射出的候选文档（不依赖节点级开关），使三方（baseline / 节点级 / 文档级）可对比

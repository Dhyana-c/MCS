# query-rerank Specification

## Purpose

提供查询输出相关性重排插件，按查询文本对节点打分、降序重排并截断 top-N，内置词法打分器，打分器接口可插拔替换为嵌入/LLM 方案。

## Requirements

### Requirement: 查询输出相关性重排插件

The system SHALL provide a `query_postprocess` plugin that reranks, filters, and truncates the `query()` result `List[Node]` by relevance to the query.

#### Scenario: 按相关性重排节点

- **WHEN** 该插件挂载于 `query_postprocess` 且 `query()` 产生一组 `List[Node]`
- **THEN** 插件 MUST 用 `ctx.user_input`（查询文本）给每个节点打相关性分，并 MUST 按分降序返回重排后的 `List[Node]`

#### Scenario: 过滤低相关并截断 top-N

- **WHEN** 候选节点数超过配置的 top-N，或部分节点相关性低于阈值
- **THEN** 插件 MUST 丢弃低于阈值的节点并截断到 top-N；默认配置 MUST 保守（以排序为主、宽松截断，避免误杀）

#### Scenario: 打分器可插拔

- **WHEN** 检查打分器
- **THEN** 框架 MUST 提供一个打分器接口 `score(query: str, node: Node) -> float`；MUST 至少实装一个**词法**打分器（查询与节点 name/content 的 token 重叠，零额外 LLM 调用）；接口 MUST 允许替换为嵌入/LLM 打分器

---

### Requirement: LexicalScorer 仅从 node.content 提取词法 token

`LexicalScorer` MUST NOT 从 `node.extensions["statements"]["items"]` 读取额外文本。所有词法匹配信息 MUST 来自 `node.content` 单一来源（content 已包含全部关系信息）。缓存 key MUST 包含 content hash 以适配 merge 原地改写。

#### Scenario: scoring 不使用 statements

- **WHEN** LexicalScorer 对节点打分
- **THEN** 词法 token MUST 仅从 `node.name` 和 `node.content` 提取
- **AND** MUST NOT 读取 `extensions["statements"]`

#### Scenario: 缓存 key 含 content hash

- **WHEN** `LexicalScorer` 缓存节点的 token set
- **THEN** 缓存 key MUST 包含 `(node_id, content_hash)` 以确保 merge 原地改写 content 后缓存自动失效
- **AND** `content_hash` MUST 基于 `node.content` 的哈希值（如 `hash(node.content or "")`）

#### Scenario: merge 后缓存自动 miss

- **WHEN** 节点 content 被 `_dispatch_merge` 原地改写
- **AND** 后续查询中 `LexicalScorer.score()` 被调用
- **THEN** 由于 content_hash 变化，MUST 发生 cache miss 并重新分词

#### Scenario: 默认 opt-in

- **WHEN** 未显式启用该插件
- **THEN** 框架 MUST NOT 改变既有默认查询链行为（`query()` 返回与现状一致）

#### Scenario: 空结果透传

- **WHEN** `query()` 结果为空列表
- **THEN** 插件 MUST 返回空列表，不报错

---

### Requirement: LexicalScorer 维护节点 token set 缓存

`LexicalScorer` SHALL 维护内部 `_token_cache: dict[str, tuple[set[str], set[str]]]` 缓存，以 `node.id` 为键存储 `(name_tokens, content_tokens)`。`score` 方法 MUST 优先查缓存；未命中时现场分词并写入缓存。

#### Scenario: 缓存命中时跳过分词

- **WHEN** `score(query, node)` 被调用且 `node.id` 在 `_token_cache` 中
- **THEN** MUST 使用缓存的 `(name_tokens, content_tokens)`，MUST NOT 调用 `_tokenize`

#### Scenario: 缓存未命中时分词并缓存

- **WHEN** `score(query, node)` 被调用且 `node.id` 不在 `_token_cache` 中
- **THEN** MUST 对 node.name 和 node.content 分别调用 `_tokenize`，将结果写入 `_token_cache[node.id]`

#### Scenario: 缓存生命周期为查询期

- **WHEN** 一次 `query()` 调用开始
- **THEN** `_token_cache` 可为空或保留上次查询的缓存（节点内容在查询间不变，缓存仍有效）

#### Scenario: 跨查询缓存有效

- **WHEN** 节点 N 在查询 Q1 中被分词并缓存，查询 Q2 也涉及节点 N
- **THEN** Q2 MUST 命中 Q1 的缓存，MUST NOT 重新分词

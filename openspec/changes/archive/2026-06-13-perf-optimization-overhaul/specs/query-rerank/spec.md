## ADDED Requirements

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

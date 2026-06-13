## MODIFIED Requirements

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

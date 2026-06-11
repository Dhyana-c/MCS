## MODIFIED Requirements

### Requirement: LexicalScorer 仅从 node.content 提取词法 token

`LexicalScorer` MUST NOT 从 `node.extensions["statements"]["items"]` 读取额外文本。所有词法匹配信息 MUST 来自 `node.content` 单一来源（content 已包含全部关系信息）。

#### Scenario: scoring 不使用 statements

- **WHEN** LexicalScorer 对节点打分
- **THEN** 词法 token MUST 仅从 `node.name` 和 `node.content` 提取
- **AND** MUST NOT 读取 `extensions["statements"]`

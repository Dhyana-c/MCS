## ADDED Requirements

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

#### Scenario: 默认 opt-in

- **WHEN** 未显式启用该插件
- **THEN** 框架 MUST NOT 改变既有默认查询链行为（`query()` 返回与现状一致）

#### Scenario: 空结果透传

- **WHEN** `query()` 结果为空列表
- **THEN** 插件 MUST 返回空列表，不报错

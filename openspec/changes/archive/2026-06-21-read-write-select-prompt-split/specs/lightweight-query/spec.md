## ADDED Requirements

### Requirement: 写管线关联定位使用窄召回 select_facts_write

`query_nodes()`（供写管线阶段② 关联节点定位复用）在执行遍历阶段时 SHALL 以 `select_purpose="select_facts_write"` 调用 `_traverse`，使写侧事实筛选使用**窄召回**口径，与读侧 `query()` 的宽召回 `select_facts` 解耦。框架 SHALL 在 `mcs.prompts.DEFAULT_PROMPTS` 注册默认 `select_facts_write` bundle（窄召回：选最相关、优先具体信息、可返回空），其 `parse` 与 `select_facts` 等价（同为编号 JSON 数组解析）。

写侧窄召回的目的：阶段② 产出的关联节点喂给 `extract_concepts` / `judge_relations` 做"已有节点对齐"（合并同义、判互斥），需高精度——宽召回会拉入弱相关节点、抬高错并 / 错判互斥率、污染图结构。

#### Scenario: query_nodes 走 select_facts_write

- **WHEN** `query_nodes("text")` 进入遍历阶段的事实筛选
- **THEN** 框架 MUST 以 `purpose="select_facts_write"` 调用 LLM；MUST NOT 使用读侧的 `select_facts`

#### Scenario: 默认注册 select_facts_write

- **WHEN** 导入 `mcs.prompts.DEFAULT_PROMPTS`
- **THEN** MUST 含 `select_facts_write` 条目；其 `parse` MUST 与 `select_facts` 的 `parse` 行为一致（同样解析编号 JSON 数组、同样抛 `LLMParseError`）

#### Scenario: 读写 purpose 各自独立可覆盖

- **WHEN** 用户经 `MCSConfig.prompt_overrides` 覆盖 `select_facts`（或 `select_facts_write`）其中之一
- **THEN** 另一个 purpose MUST 不受影响（读写 prompt 正交）

#### Scenario: 空结果不阻塞写入

- **WHEN** 窄召回下 `query_nodes` 返回空列表
- **THEN** `ctx.related` MUST 为空列表；框架 MUST 继续执行写管线阶段③（与现有行为一致）

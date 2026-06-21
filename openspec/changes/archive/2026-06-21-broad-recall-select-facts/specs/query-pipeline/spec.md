## ADDED Requirements

### Requirement: select_facts 采用宽召回口径

读路径阶段 ③ 的事实筛选（`purpose=select_facts`）SHALL 采用**宽召回**口径：只要候选事实条目涉及查询中的任何实体、主题、时间、比较对象或其关联事实，就应纳入，宁可多召回交由后续裁剪 / 重排收敛，MUST NOT 因"没有哪一条直接回答了查询"而漏选或返回空。候选事实条目不少于 5 条时，SHALL 至少返回 3 条最相关的。默认 `select_facts` prompt bundle（`mcs.prompts.select_facts.SYSTEM_PROMPT` / `USER_TEMPLATE`）MUST 体现此宽召回口径。

宽召回引入的噪声由查询管线后续阶段（`doc_rerank` / 裁剪）收敛，不在筛选步处理。

> 注：本口径**仅约束读路径**。写管线阶段 ② 关联定位使用独立的窄召回 `select_facts_write`（见 `read-write-select-prompt-split`），不受本口径约束。

#### Scenario: 宽召回宁可多选

- **WHEN** 候选中存在与查询实体 / 主题 / 时间 / 比较对象相关的条目，但无任一条直接回答查询
- **THEN** `select_facts` MUST 仍返回这些相关条目，MUST NOT 返回空

#### Scenario: 候选充足时下限返回

- **WHEN** 候选事实条目不少于 5 条且存在相关项
- **THEN** `select_facts` SHALL 至少返回 3 条最相关条目

#### Scenario: 默认 prompt 体现宽召回

- **WHEN** 导入 `mcs.prompts.DEFAULT_PROMPTS["select_facts"]`
- **THEN** 其 system / template MUST 体现"宽召回、宁多勿漏"口径，MUST NOT 是"仅选最相关、无相关可返回空"的窄召回口径

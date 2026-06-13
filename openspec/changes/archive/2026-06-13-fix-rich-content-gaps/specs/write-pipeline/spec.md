## MODIFIED Requirements

### Requirement: merge 时 concept content 追加到目标节点

`_dispatch_merge` 在合并概念时，MUST 将 `decision.concept.content` 追加到目标节点的 `content` 字段（而非写入 statements extensions）。追加后若 content 超过阈值，MUST 触发 LLM 压缩。

#### Scenario: merge 追加 content

- **WHEN** merge decision 的 `concept.content` 非空
- **AND** `concept.content` 不是目标节点 `content` 的子串
- **THEN** write_pipeline MUST 将 `concept.content` 以换行符追加到目标节点的 `content`

#### Scenario: merge 跳过重复 content

- **WHEN** merge decision 的 `concept.content` 已经是目标节点 `content` 的子串
- **THEN** write_pipeline MUST NOT 重复追加

#### Scenario: merge 后 content 超阈值触发压缩

- **WHEN** merge 追加 content 后目标节点 `content` 长度超过 `merge_content_threshold`（默认 500）
- **THEN** write_pipeline MUST 调用 `gen_summary` purpose 对 content 进行压缩重写
- **AND** 压缩后 content 长度 MUST <= threshold

#### Scenario: merge 压缩失败降级

- **WHEN** merge 后 content 超阈值但压缩 LLM 调用失败
- **THEN** write_pipeline MUST 保留追加后的原始 content 并记录 warning 日志

### Requirement: 阶段 ④ DecisionList 动作类型简化

阶段 ④ `judge_relations` 的 DecisionList 从 4 种动作简化为 3 种：`merge`、`create`、`no_op`。`attach_statement` 标记为 deprecated，保留在动作类型字面量中但不再由管线产生。merge 决策中 `aliases_to_add` 字段用于让 LLM 贡献额外别名。

#### Scenario: DecisionList 不再产生 attach_statement

- **WHEN** 阶段 ④ LLM 返回 `action: "attach_statement"`
- **THEN** write_pipeline MUST 将其视为 no-op（不执行任何图操作），并记录 deprecation 警告日志

#### Scenario: DecisionList 不再使用 initial_statements

- **WHEN** 阶段 ④ LLM 返回 `initial_statements` 字段
- **THEN** write_pipeline MUST 忽略该字段，不写入 `extensions["statements"]`

#### Scenario: merge 动作含 aliases_to_add

- **WHEN** ④ 决定一个概念已存在为节点 X
- **THEN** DecisionList 中 MUST 含一项 `{action: "merge", concept: c, target_id: X_id, aliases_to_add: [...]}`
- **AND** `aliases_to_add` MUST 包含 LLM 识别的同义词、缩写、变体写法

#### Scenario: create 动作

- **WHEN** ④ 决定一个概念是新概念
- **THEN** DecisionList 中 MUST 含一项 `{action: "create", concept: c, edges_to: [anchor_ids]}`

#### Scenario: no_op 动作

- **WHEN** ④ 决定某概念不值得入图（如太宽泛或与现有图无关）
- **THEN** DecisionList 中 MUST 含一项 `{action: "no_op", concept: c, reason: "..."}`；⑤ 跳过该项

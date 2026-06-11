## MODIFIED Requirements

### Requirement: 阶段 ④ DecisionList 动作类型简化

阶段 ④ `judge_relations` 的 DecisionList 从 4 种动作简化为 3 种：`merge`、`create`、`no_op`。`attach_statement` 标记为 deprecated，保留在动作类型字面量中但不再由管线产生。

#### Scenario: DecisionList 不再产生 attach_statement

- **WHEN** 阶段 ④ LLM 返回 `action: "attach_statement"`
- **THEN** write_pipeline MUST 将其视为 no-op（不执行任何图操作），并记录 deprecation 警告日志

#### Scenario: DecisionList 不再使用 initial_statements

- **WHEN** 阶段 ④ LLM 返回 `initial_statements` 字段
- **THEN** write_pipeline MUST 忽略该字段，不写入 `extensions["statements"]`

---

### Requirement: merge 时 concept content 追加到目标节点

`_dispatch_merge` 在合并概念时，MUST 将 `decision.concept.content` 追加到目标节点的 `content` 字段（而非写入 statements extensions）。

#### Scenario: merge 追加 content

- **WHEN** merge decision 的 `concept.content` 非空
- **AND** `concept.content` 不是目标节点 `content` 的子串
- **THEN** write_pipeline MUST 将 `concept.content` 以换行符追加到目标节点的 `content`

#### Scenario: merge 跳过重复 content

- **WHEN** merge decision 的 `concept.content` 已经是目标节点 `content` 的子串
- **THEN** write_pipeline MUST NOT 重复追加

---

### Requirement: create 时不再写入 statements

`_dispatch_create` 在创建新节点时，MUST NOT 将 `initial_statements` 写入 `node.extensions["statements"]`。节点的 `content` 已由 `extract_concepts` prompt 保证包含充分信息。

#### Scenario: create 不写入 statements

- **WHEN** create decision 带有 `initial_statements` 字段
- **THEN** write_pipeline MUST 忽略该字段，新节点无 statements extension

---

### Requirement: 概念提取生成自包含描述

阶段 ③ `extract_concepts` 的 prompt MUST 指导 LLM 为每个概念生成 2-4 句自包含描述，覆盖概念定义、关键事实、与其他实体的关系、来源上下文。不再接受只有一句话的简短定义。

#### Scenario: concept content 包含丰富信息

- **WHEN** extract_concepts 从文档中提取概念
- **THEN** 每个概念的 `content` MUST 包含至少 2 句话，覆盖概念定义及关键事实/关系

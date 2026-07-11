## RENAMED Requirements

- FROM: `### Requirement: merge 时 concept content 追加到目标节点`
- TO: `### Requirement: merge 时 concept content 语义合并到目标节点`

## MODIFIED Requirements

### Requirement: 概念提取生成精简自包含描述

阶段 ③ `extract_concepts` 的 prompt MUST 指导 LLM 生成**精简**的自包含**概念/事实**描述：仅含定义 + 短叶子属性，控制在 **lean 基线**（**~24 token**）。关系语义 MUST NOT 写入概念 `content`——关系由**命题（事实）节点**承载（谓词落其 content）。

**时间归属**（落实 `unified-graph-schema` 时间归属不变量，按节点类型分）：
- **概念 `content` 零时间**：MUST NOT 含任何时间（无论相对「今天/这次/未完成/计划中/将进行」还是固定「1976 年」）；prompt MUST NOT 鼓励「日期」进概念 content。
- **事实 `content` 禁相对/单次时间、允许固定历史时间**：MUST NOT 含「今天/这次」等事件性时间；MAY 含「1976 年」等固定历史时间作命题属性。
- 带时间的发生 MUST 去时间化作事实（「今天去按摩」→ 事实「用户去按摩」，时间归事件层）。
- MUST NOT 抽事件性命题（「X 的情况」、某次因果「X 导致 Y」）或偏好/模式（「喜欢 X」）作概念/事实 —— 事件性归事件层、偏好靠 degree 涌现。

#### Scenario: 概念 content 精简且不含关系叙述

- **WHEN** `extract_concepts` 提取一个概念
- **THEN** 其 `content` MUST 仅含定义 + 短属性，MUST NOT 含成句关系叙述（关系归命题节点）

#### Scenario: 概念 content 零时间

- **WHEN** `extract_concepts` 提取一个概念（如"按摩"、"苹果公司"）
- **THEN** 其 `content` MUST NOT 含任何时间词（相对「今天/这次」与固定「1976 年」都禁）
- **AND** prompt MUST NOT 鼓励「日期」作概念叶子属性

#### Scenario: 事实 content 禁单次时间、允许固定历史时间

- **WHEN** 输入含带时间的发生（如"今天去按摩"、"苹果创立于 1976"）
- **THEN** 事实 `content` MUST NOT 含「今天/这次」等相对/单次时间
- **AND** MAY 含「1976 年」等固定历史时间作命题属性
- **AND** 「今天去按摩」MUST 去时间化作事实「用户去按摩」（时间归事件层）

#### Scenario: 事件性/偏好性命题不进核心图

- **WHEN** 输入含事件性命题（如「未去按摩的情况」）或偏好陈述（如「喜欢按摩」）
- **THEN** `extract_concepts` MUST NOT 抽其作概念/事实
- **AND** 事件性命题归事件层；偏好靠概念被多事件背书 degree 涌现

---

### Requirement: merge 时 concept content 语义合并到目标节点

`_dispatch_merge` 在合并概念时，MUST 将 `decision.concept.content` 与目标节点 `content` **语义合并**为一个稳定定义（LLM 合并：去重、择优、守时间归属），MUST NOT 机械追加（换行拼接）。合并 MUST 按目标节点类型分流时间归属（合并 purpose 携带 `node_class`）：概念 content 零时间；事实 content 禁相对/单次时间、MUST 保留固定历史时间（命题固有属性不得丢弃）。合并后 content 仍 MUST 守时间归属不变量。语义合并结果若超 `merge_content_threshold`，MUST 触发 `merge-content-compaction` 的压缩段（见该 capability —— 前提已从「追加后」协调为「合并后」）。

#### Scenario: merge 语义合并 content

- **WHEN** merge decision 的 `concept.content` 非空且与目标节点 `content` 语义不同
- **THEN** write_pipeline MUST 调用 LLM 将两者语义合并成一个稳定定义写入目标 `content`
- **AND** MUST NOT 换行拼接

#### Scenario: merge 跳过语义重复 content

- **WHEN** merge decision 的 `concept.content` 已是目标节点 `content` 的子串或语义重复
- **THEN** write_pipeline MUST NOT 重复合并（保留目标 content）

#### Scenario: merge 后 content 守时间归属

- **WHEN** merge 合并 content
- **THEN** 合并后 content MUST 守时间归属不变量（概念零时间、事实禁相对/单次时间）
- **AND** 合并 purpose MUST 携带目标节点 `node_class` 分流：目标为事实节点时，固定历史时间（如「1976 年」）MUST 保留，MUST NOT 按概念零时间规则抹掉

#### Scenario: merge 合并失败降级

- **WHEN** merge 时 LLM 合并调用失败
- **THEN** write_pipeline MUST 保留目标节点已有 content（不追加新 content）并记录 warning 日志

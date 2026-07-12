## ADDED Requirements

### Requirement: 作品叙事事件抽取产出 WorkEventDraft

系统 SHALL 在 `mcs.entities.decisions` 暴露 `WorkEventDraft` dataclass——作品叙事事件 LLM 抽取的产出（字段 `name: str`、`content: str`、`narr_timestamp: str | None`（作品纪年，如"200 年" / "建安五年"）、`participants: list[str]`）。`WorkEventDraft` 与 `EventData`（不经 LLM 的规则入库结构输入）、`ConceptDraft`（概念 / 事实抽取产出）并列，语义不混：作品叙事事件走 LLM 产 `WorkEventDraft`、摄入行为事件走规则产 `EventData`。`EventData.timestamp` 约定放宽为"universe 内时间语义字符串"（现实 ISO / 作品纪年），不再强制 ISO 8601。

#### Scenario: decisions 导出 WorkEventDraft

- **WHEN** 加载 `mcs.entities.decisions`
- **THEN** 存在 `WorkEventDraft` dataclass（字段 `name, content, narr_timestamp, participants`）
- **AND** `WorkEventDraft` 与 `EventData`、`ConceptDraft` 并列、语义不混（作品事件 LLM 抽取产出 / 规则入库 / 概念事实抽取）

#### Scenario: WorkEventDraft 不复用 EventData / ConceptDraft

- **WHEN** 作品叙事事件经 LLM 抽取
- **THEN** MUST 产 `WorkEventDraft`（带 `narr_timestamp` 作品纪年）
- **AND** MUST NOT 复用 `EventData`（其语义为"不经 LLM 的规则入库"）/ `ConceptDraft`（无 timestamp、语义为概念 / 事实）

#### Scenario: EventData.timestamp 约定放宽

- **WHEN** 查看 `EventData.timestamp` 语义
- **THEN** MUST 为"universe 内时间语义字符串"（现实 ISO / 作品纪年），不再强制 ISO 8601

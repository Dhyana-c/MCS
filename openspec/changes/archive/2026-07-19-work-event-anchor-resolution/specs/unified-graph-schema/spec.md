# unified-graph-schema delta — 叙事时间戳锚点解析

## ADDED Requirements

### Requirement: 叙事时间戳锚点解析（日精度）

作品叙事事件抽取（③b `extract_work_events`）的 `narr_timestamp` SHALL 默认保留原文形态、不换算、不猜测（现行规则）；**唯一例外**：作品文本自带**显式时间锚点**（如逐行 `[1:56 pm on 8 May, 2023]` 标记）、发生时间为**相对锚点的表述**（yesterday / two days ago / 前天）、且经纯日期算术能**确定到具体某天**时，`narr_timestamp` MAY 解析为 ISO 日期形态（`YYYY-MM-DD`）。确定不了具体某天（如 "last week" / "last year"）MUST 保留原文形态（MUST NOT 编造日期）；解析产物 MUST NOT 使用年/月截断形态（`"2023-05"` / `"2022"`——与 ISO 日期分属两把排序尺子，同 universe 混排错乱，年/月精度归 Phase 2 纪年归一化）。无锚点文本与作品纪年（"建安五年"类）行为 MUST 保持不变。

#### Scenario: 锚点在场的相对时间解析为 ISO

- **WHEN** 以 `work_id` ingest 文本 `"[1:56 pm on 8 May, 2023] Sarah: I went to a support group yesterday"`，LLM 按规则解析
- **THEN** 叙事事件 `narr_timestamp` MAY 为 `"2023-05-07"`（ISO 日期），落 `event_meta.timestamp` 后 `timestamp_sort_value` MUST 非 -inf（可排序），`narrative_timeline` 按日期正确排序

#### Scenario: 确定不了具体某天则保留原文

- **WHEN** 锚点在场但相对表述无法定位到具体某天（如 "last week"）
- **THEN** `narr_timestamp` MUST 保留原文形态（如 `"last week"`），MUST NOT 编造具体日期，MUST NOT 写年/月截断形态

#### Scenario: 无锚点作品纪年行为不变

- **WHEN** 以 `work_id` ingest 无显式时间锚点的作品文本（如 "建安五年，曹操……"）
- **THEN** `narr_timestamp` MUST 保留原文形态（`"建安五年"`），MUST NOT 换算——与本 requirement 引入前行为一致

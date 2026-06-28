# agent-consolidation Specification

## Purpose
TBD - created by archiving change agent-consolidation. Update Purpose after archive.
## Requirements
### Requirement: 读取当天碎片 MD
整合管线 SHALL 经 Slice 1 的 `FragmentStore.read(date)` 读取指定日期的完整碎片内容作为输入。文件不存在时 SHALL 视为空内容（不报错、不入图）。

#### Scenario: 正常读取
- **WHEN** 整合 2026-06-27，碎片文件存在且有多行
- **THEN** 读取完整内容作为整合输入

#### Scenario: 文件不存在
- **WHEN** 整合 2026-06-27，碎片文件不存在
- **THEN** 视为空，整合结果"无内容可整合"，不入图

### Requirement: 逐行解析为碎片序列
整合管线 SHALL 把当天 MD 逐行解析为 `(timestamp, content)`：行格式 `HH:MM 内容`，timestamp 由文件名日期 + 行内 `HH:MM` 组成 ISO 8601，content 为时间之后的正文（不含时间前缀）。无法解析的行 SHALL 跳过并记 WARNING、不中断。解析 SHALL NOT 调 LLM、SHALL NOT 做语义分段。

#### Scenario: 正常解析
- **WHEN** MD 含多行 `HH:MM 内容`
- **THEN** 逐行解析为带各自 ISO timestamp 与正文的碎片序列

#### Scenario: 跳过格式错误行
- **WHEN** 某行不符 `HH:MM 内容`
- **THEN** 跳过该行、记 WARNING，继续其余行

#### Scenario: 空碎片
- **WHEN** 当天碎片为空或仅空白
- **THEN** 跳过，不入图

### Requirement: 去噪筛选（Consolidator 应用层前置）
整合管线 SHALL 在 `Consolidator` 内部、**`ingest` 调用之前**对每条解析出的碎片做去噪判定，丢弃噪声 / 不值得记的碎片，仅把保留的碎片送 `ingest`。去噪 SHALL NOT 实现为 `WRITE_PREPROCESS` 插件——该插件契约纯变换、`MUST NOT control pipeline flow (e.g. skip)`（[plugin-protocol spec:108](../../specs/plugin-protocol/spec.md)），丢不掉输入；去噪须在管线外应用层执行。去噪 SHALL NOT 做合成 / 同义合并 / 概念抽取——这些交 `mcs.ingest` 的概念层。去噪只作用于整合路径，SHALL NOT 影响 agent 直接 `learn` 等其他写入路径。

#### Scenario: 噪声不入图
- **WHEN** 当天碎片含明显闲聊 / 噪声行
- **THEN** 该噪声碎片不产生事件（被去噪丢弃）

#### Scenario: 去噪不合成不归并
- **WHEN** 当天多条碎片讲同一件事的不同片段，且都值得记
- **THEN** 去噪 MUST 各自保留为独立碎片（MUST NOT 合成为一条）；归并 / 同义合并由后续 ingest 概念层承担

#### Scenario: 去噪保守
- **WHEN** 某碎片是否值得记拿不准
- **THEN** 倾向保留（不误杀），原始碎片在 MD 保真层可追

#### Scenario: 去噪不改写 content
- **WHEN** 去噪判定一条碎片
- **THEN** 去噪 MUST 只判去留（keep / drop），MUST NOT 改写 / 润色 / 摘要 content
- **AND** 送 `ingest_structured` 的 content MUST == 解析原文（去噪器输出不参与 content 构造）

### Requirement: 保留碎片逐条入图（一碎片一事件）
每条**保留**的碎片 SHALL 经 `MemoryStore.ingest_structured(content, timestamp)` **逐条**入图：一碎片一事件，事件时间 = 碎片 timestamp（落 `event_meta.timestamp`），content 仅正文。整合管线 SHALL 收集每条返回的事件 id。单条 ingest 失败 SHALL 记错误日志并续跑（不中断）。LLM 去噪判定 SHALL NOT 在 MCS worker 线程内执行（仅 `ingest_structured`/`recall` 等碰 MCS 的调用经 worker）。

#### Scenario: N 条保留碎片建 N 个事件
- **WHEN** 去噪后保留 N 条碎片
- **THEN** 依次 N 次 `ingest_structured`，建 N 个事件节点，收集 N 个事件 id（不合成、不少建）

#### Scenario: 事件时间为碎片时间
- **WHEN** 一条碎片 timestamp 为当天 14:30
- **THEN** 对应事件 `event_meta.timestamp` 为当天 14:30 的 ISO（非整合时刻），无塌缩

#### Scenario: 单条失败计数（不掩盖为 done）
- **WHEN** 某条 ingest 抛错
- **THEN** 记错误日志、失败计数 +1，继续后续碎片（不中断整个整合）
- **AND** 当日若有任一碎片失败，终态 MUST 为 `failed`（MUST NOT 掩盖为 `done`）；详见「整合部分失败可见化与幂等重试」

### Requirement: 整合幂等性（单日锁定）
整合管线 SHALL 由 `ConsolidationTracker` 保证同一日期最多整合一次：某日 `done` 后锁定，再触发 SHALL 返回 `already`、不重跑。SHALL NOT 提供 force / 重整 / 历史日期重整。

#### Scenario: 首次整合
- **WHEN** 2026-06-27 首次整合
- **THEN** 正常去噪 + 逐条入图，tracker 记该日 `done` + 事件数

#### Scenario: 重复整合被拒
- **WHEN** 2026-06-27 已 `done`，再触发
- **THEN** 返回 `already`，不重复入图

#### Scenario: 已整合后改 MD
- **WHEN** 2026-06-27 已 `done`，用户改 MD 后再触发
- **THEN** 仍拒、不重整（改动只留 MD 保真层）——单日锁定的明确取舍

### Requirement: 整合部分失败可见化与幂等重试

整合管线 SHALL 让部分失败可见、可幂等补整（区别于 `done` 的锁死）：当日若任一保留碎片 `ingest_structured` 失败，终态 SHALL 为 `failed`（MUST NOT 掩盖为 `done`），响应 SHALL 附 `failures` 计数。`ConsolidationTracker` SHALL 持久化已成功碎片的 `timestamp` 集合（`succeeded_ts`）。`failed` 状态 SHALL 允许重入整合：重跑时 SHALL 跳过 `succeeded_ts` 中的碎片（幂等去重、不重复入图）；重跑全成功后 SHALL 转 `done` 并清空 `succeeded_ts`。`done` / `running` 仍拒重入（见「整合幂等性（单日锁定）」）。

#### Scenario: 部分失败标 failed 且持久化已成功碎片
- **WHEN** 当日 3 条保留碎片，其中 1 条 ingest 失败
- **THEN** 终态 MUST 为 `failed`、响应 `failures == 1`、`events == 2`（成功条数）
- **AND** tracker 持久化的 `succeeded_ts` MUST 含 2 条成功碎片的 timestamp

#### Scenario: failed 可重试且幂等去重
- **WHEN** 某日 `failed`（A、C 成功、B 失败），再次触发整合且 B 这次成功
- **THEN** MUST 仅对 B 调用 `ingest_structured`（A、C 被跳过、不重复入图）
- **AND** 终态 MUST 转 `done`、`events == 3`，`succeeded_ts` MUST 清空

#### Scenario: failed 重试仍失败保持 failed
- **WHEN** 某日 `failed`，重试时失败碎片仍未补齐
- **THEN** 终态 MUST 保持 `failed`，已成功碎片的 `succeeded_ts` MUST 不丢、且不重复入图

### Requirement: 整合状态追踪与持久化
系统 SHALL 记录每日整合状态（日期 / 状态 / 事件数 / 时间戳）并持久化到本地 JSON（默认 `~/.mcs_memory/consolidation_status.json`）。进程重启后 SHALL 恢复。

#### Scenario: 查询已整合
- **WHEN** 查询 2026-06-27 状态
- **THEN** 返回 `{"date": "2026-06-27", "status": "done", "events": 5, "consolidated_at": "..."}`

#### Scenario: 查询未整合
- **WHEN** 查询从未整合的日期
- **THEN** 返回 `{"date": "...", "status": "pending"}`

#### Scenario: 重启恢复
- **WHEN** 进程重启，之前已整合 2026-06-27
- **THEN** 读持久化文件后该日仍 `done`

### Requirement: 整合 API（挂 mcs_agent app，优雅降级）
系统 SHALL 提供 `POST /consolidate`（无 force；**无 date 默认整合「昨天」**；已整合 → `already`）、`GET /consolidate/status?date=...`（单日）、`GET /consolidate/statuses`（全量，供 Slice 4 日历）。整合需 MCS / LLM；当注入的 agent 无 `memory` / `llm` 时（如裸 fake agent）相关端点 SHALL 返回 503，不影响捕获等其他路由。整合**今天**（`date` = 当天）SHALL 在响应附 `warning`，提示今天整合后即锁定、后续消息不会自动入图。

#### Scenario: 默认整合昨天
- **WHEN** `POST /consolidate`，body `{}`
- **THEN** 默认整合**昨天**（与调度器一致），返回该日结果

#### Scenario: 显式整合昨天
- **WHEN** `POST /consolidate`，body `{"date": "<昨天>"}`，未整合
- **THEN** 执行整合，返回 `{"ok": true, "date": "<昨天>", "events": 5, "status": "done"}`

#### Scenario: 整合今天须显式且带 warning
- **WHEN** `POST /consolidate`，body `{"date": "<今天>"}`
- **THEN** 执行整合，返回结果 MUST 含 `warning`（今天整合后即锁、后续消息不自动入图）

#### Scenario: 已整合再触发
- **WHEN** `POST /consolidate`，该日已 `done`
- **THEN** 返回 `{"ok": true, "date": "...", "status": "already"}`

#### Scenario: 全量状态
- **WHEN** `GET /consolidate/statuses`
- **THEN** 返回所有已知日期的状态列表（供日历渲染 done / pending / failed）

#### Scenario: 无 memory 优雅降级
- **WHEN** app 以无 `memory` 的 fake agent 构建，调 `POST /consolidate`
- **THEN** 返回 503，MUST NOT 抛未捕获异常，且不影响 `/note` 等捕获路由


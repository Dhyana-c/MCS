## ADDED Requirements

### Requirement: 确认即 ingest 协调（confirm_one）
`Consolidator` SHALL 提供 `confirm_one(id)` 协调单条碎片确认入图，串联碎片层状态原语（fragment-capture）与 `ingest`：

1. `fragment_store.begin_confirm(id)` 原子抢占 `pending → confirming`；碎片非 `pending`（已 `confirming`/`confirmed`）SHALL 幂等返回（不 `ingest`、不重复入图）。
2. `memory.ingest_structured(content, timestamp)` → 拿 `event_id`。
3. `fragment_store.confirm_mark(id, event_id)` 落 `confirming → confirmed`。
4. `ingest` 失败 SHALL 调 `fragment_store.abort_confirm(id)` 回退 `confirming → pending`、返回失败（可重试），MUST NOT 留 `confirming` 悬空。

`ingest_structured` SHALL 经 MCS worker 线程执行（仅碰 MCS 的调用经 worker）；`begin_confirm`/`confirm_mark`/`abort_confirm` 在 `FragmentStore` 内锁执行（文件 IO 旁路、不进 worker）。

#### Scenario: 确认 pending 入图
- **WHEN** `confirm_one(id)`，碎片 pending
- **THEN** begin_confirm 置 confirming → ingest 拿 event_id → confirm_mark 置 confirmed + event_id；返回 `{ok, id, status:"confirmed", event_id}`

#### Scenario: 已 confirming/confirmed 幂等返回
- **WHEN** `confirm_one(id)`，碎片已 confirming 或 confirmed
- **THEN** 不 ingest，返回幂等结果（不重复入图）

#### Scenario: ingest 失败回退 pending
- **WHEN** `confirm_one(id)` 中 `ingest_structured` 抛错
- **THEN** abort_confirm 回退 pending、event_id 保持 null，返回失败（可重试）

### Requirement: 单条确认 API（POST /fragments/{id}/confirm）
系统 SHALL 提供 `POST /fragments/{id}/confirm`：调 `Consolidator.confirm_one(id)`，返回 `{ok, id, status, event_id}`。该端点 SHALL 挂在 `mcs_mem` app，与捕获端点同居。需 `memory`；agent 无 `memory` 时 SHALL 返回 503，不影响 `/note` 等捕获路由。碎片 id 不存在 SHALL 返回 404。

#### Scenario: 确认成功
- **WHEN** `POST /fragments/{id}/confirm`，碎片 pending
- **THEN** 调 confirm_one，返回 `{ok:true, id, status:"confirmed", event_id}`

#### Scenario: 无 memory 优雅降级
- **WHEN** app 以无 `memory` 的 fake agent 构建，调 `POST /fragments/{id}/confirm`
- **THEN** 返回 503，MUST NOT 抛未捕获异常，且不影响 `/note` 等路由

#### Scenario: 碎片不存在
- **WHEN** `POST /fragments/{id}/confirm`，该 id 无碎片
- **THEN** 返回 404

### Requirement: 并发确认不重复入图（CAS）
确认 SHALL 经 `begin_confirm` 的 `pending → confirming` CAS 保证：并发确认同一条碎片时，仅一个请求抢占成功并 `ingest`，其余抢占失败（碎片已 `confirming`/`confirmed`）、MUST NOT 重复 `ingest` / 建重复事件。批量整合（`consolidate`）与单条确认（`POST /fragments/{id}/confirm`）并发作用于同一条碎片时同理——仅一方 `ingest`。

#### Scenario: 并发确认同一条仅一个入图
- **WHEN** 两个请求并发 `POST /fragments/{id}/confirm` 同一条 pending 碎片
- **THEN** 仅一个 `ingest_structured` 成功建事件，另一个抢占失败、不重复入图

#### Scenario: 抢占失败者不重复入图
- **WHEN** 一条碎片正 confirming（被某请求占用），另一请求确认它
- **THEN** 该请求 begin_confirm 抢占失败、幂等返回，MUST NOT 调 ingest

## REMOVED Requirements

### Requirement: 逐行解析为碎片序列
**Reason**: 碎片已是结构化对象（每条自带独立 timestamp），整合不再需要从 MD 逐行解析。`parse_fragments` 仅保留作 MD→JSONL 迁移用途（位于 `mcs_mem/fragments.py` 碎片层），不在整合运行路径使用。
**Migration**: 整合直接读结构化碎片（`FragmentStore` 的 pending 碎片），无需解析步骤。

### Requirement: 去噪筛选（Consolidator 应用层前置）
**Reason**: 过滤职责交回用户——用户删除不要的 `pending` 碎片，幸存的由 scheduler 兜底 / 手动全部确认入图。自动去噪（LLM 判去留）下线，以换取入图的显式可控性（用户可见、可干预、可修正）。
**Migration**: 删除 `Denoiser` / `LLMDenoiser` 与 `mcs_mem/prompts/denoise.py`；`Consolidator` 不再注入去噪器、不再在 ingest 前做去留判定。

## RENAMED Requirements

- FROM: `### Requirement: 整合 API（挂 mcs_agent app，优雅降级）`
- TO: `### Requirement: 整合 API（挂 mcs_mem app，优雅降级）`

## MODIFIED Requirements

### Requirement: 读取当天碎片 MD
整合管线 SHALL 经 `FragmentStore` 读取指定日期的**全部 `pending` 碎片**作为待确认输入（`confirming`/`confirmed` 自然跳过 = 幂等）。该日期无碎片 / 无 pending 碎片时 SHALL 视为无可确认（不入图、返回 skipped）。

#### Scenario: 正常读取 pending
- **WHEN** 整合 2026-06-27，该日有 3 条 pending、2 条 confirmed
- **THEN** 仅取 3 条 pending 作待确认输入（confirming/confirmed 跳过）

#### Scenario: 无 pending
- **WHEN** 整合 2026-06-27，该日碎片均为 confirmed 或无碎片
- **THEN** 无可确认，返回 skipped、不入图

### Requirement: 保留碎片逐条入图（一碎片一事件）
整合 SHALL 对每条 `pending` 碎片经 `confirm_one`（见「确认即 ingest 协调」）**逐条**入图：一碎片一事件，事件时间 = 碎片 timestamp，content 仅正文。整合 SHALL 收集每条结果（confirmed / failed）。单条 `ingest` 失败 SHALL 经 `abort_confirm` 保持 `pending`、续跑（不中断、不回滚）。

#### Scenario: N 条 pending 确认建 N 个事件
- **WHEN** 整合 3 条 pending 碎片，全部成功
- **THEN** 依次 3 次 `ingest_structured`，建 3 个事件、3 条转 confirmed、收集 3 个 event_id

#### Scenario: 事件时间为碎片时间
- **WHEN** 一条碎片 timestamp 为当天 14:30
- **THEN** 对应事件 `event_meta.timestamp` 为当天 14:30 的 ISO（非整合时刻），无塌缩

#### Scenario: 单条失败保持 pending（不中断）
- **WHEN** 某条 ingest 抛错
- **THEN** abort_confirm 回退 pending、失败计数 +1，继续后续碎片（不中断）
- **AND** 终态若有失败，响应附 `failed` 计数（供重试 / 可见）

### Requirement: 整合幂等性（单日锁定）
整合 SHALL 幂等：重复整合同一日期 SHALL 跳过 `confirming`/`confirmed` 碎片（不重复入图）、仅处理 `pending`。整合 SHALL NOT 单日锁定——当天后续新记的 `pending` 可再次整合入图（不再有「已整合后改 MD 不重整」的锁死取舍）。整合 SHALL 经互斥锁防同日并发整合（运行中再触发返回"正在整合中"）；此互斥与单条 `confirm_one` 的 per-碎片 CAS（见「并发确认不重复入图」）是两层。

#### Scenario: 重复整合跳过 confirmed
- **WHEN** 2026-06-27 已整合（部分 confirmed），用户新记几条 pending 后再整合
- **THEN** 仅确认新 pending，已 confirming/confirmed 跳过（不重复入图）

#### Scenario: 无单日锁定
- **WHEN** 2026-06-27 已整合过，当天又记新 pending
- **THEN** 再次整合可确认这些新 pending（不因"已整合"拒绝）

#### Scenario: 并发互斥
- **WHEN** 整合正在执行，再触发同日整合
- **THEN** 返回"正在整合中"、不排队（互斥锁）

### Requirement: 整合部分失败可见化与幂等重试
当日若任一 pending 碎片 `ingest_structured` 失败，响应 SHALL 附 `failed` 计数，且失败碎片 SHALL 经 `abort_confirm` 保持 `pending`（可重试）。重试整合时 SHALL 仅处理仍 `pending` 的碎片（含上次失败的），已 `confirmed` 的跳过（幂等去重、不重复入图）。

#### Scenario: 部分失败保持 pending
- **WHEN** 当日 3 条 pending，其中 1 条 ingest 失败
- **THEN** 响应 `confirmed == 2`、`failed == 1`；失败那条回退 pending、2 条转 confirmed

#### Scenario: failed 可重试且幂等去重
- **WHEN** 某日上次失败（A、C 成功、B 失败），再次整合且 B 成功
- **THEN** MUST 仅对 B 调 `confirm_one`（A、C 已 confirmed 跳过、不重复入图）
- **AND** 该日无遗留 pending

### Requirement: 整合状态追踪与持久化
系统 SHALL 记录每日期「最后整合结果」`{date, last_run, confirmed, failed}` 并持久化到本地 JSON（默认 `~/.mcs_memory/consolidation_status.json`），供前端 / 日志观测。该记录 SHALL NOT 用于锁定（不再有单日 done 拒重入）。进程重启后 SHALL 恢复观测记录。

#### Scenario: 查询整合结果
- **WHEN** 查询 2026-06-27
- **THEN** 返回 `{date, last_run, confirmed, failed}`（最后整合结果）

#### Scenario: 查询未整合
- **WHEN** 查询从未整合的日期
- **THEN** 返回该日无记录（或 pending 默认）

#### Scenario: 重启恢复
- **WHEN** 进程重启，之前整合过 2026-06-27
- **THEN** 读持久化文件后仍可查到该日最后整合记录

### Requirement: 整合 API（挂 mcs_mem app，优雅降级）
系统 SHALL 提供 `POST /consolidate`（无 date 默认确认「昨天」剩余 pending）、`GET /consolidate/status?date=...`（单日观测）、`GET /consolidate/statuses`（全量观测，供日历）。响应 SHALL 含 `confirmed`/`skipped`/`failed`。整合需 MCS；当注入的 agent 无 `memory` 时相关端点 SHALL 返回 503，不影响捕获等其他路由。**今天整合无 warning**（新模型无单日锁定，今天后续 pending 仍可再整合）。

#### Scenario: 默认确认昨天 pending
- **WHEN** `POST /consolidate`，body `{}`
- **THEN** 默认确认昨天剩余 pending，返回 `{ok, date, confirmed, skipped, failed}`

#### Scenario: 显式日期
- **WHEN** `POST /consolidate`，body `{"date": "<日期>"}`
- **THEN** 确认该日期剩余 pending，返回结果

#### Scenario: 无 pending
- **WHEN** `POST /consolidate`，目标日期无 pending（全 confirmed 或无碎片）
- **THEN** 返回 `{confirmed:0, skipped:<已confirmed数>, failed:0}`

#### Scenario: 全量状态
- **WHEN** `GET /consolidate/statuses`
- **THEN** 返回所有已知日期的最后整合观测（供日历渲染）

#### Scenario: 无 memory 优雅降级
- **WHEN** app 以无 `memory` 的 fake agent 构建，调 `POST /consolidate`
- **THEN** 返回 503，MUST NOT 抛未捕获异常，且不影响 `/note` 等捕获路由

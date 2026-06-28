# consolidation-scheduler Specification

## Purpose
TBD - created by archiving change agent-consolidation. Update Purpose after archive.
## Requirements
### Requirement: 定时整合「昨天」
系统 SHALL 支持配置定时整合，默认 cron `30 0 * * *`（每天 00:30）整合**前一日**碎片。调度时间用 cron 表达式配置；定时作业整合的目标日期 SHALL 为「昨天」（已完整封口的那天），而非当天。

> 为何整合昨天而非当天：若夜间整合当天并单日锁定，当天后续（锁定后）记的碎片会成孤儿、永不入图。整合昨天时该天已无新消息，根除孤儿。

#### Scenario: 默认定时整合昨天
- **WHEN** 系统启动，未配置自定义调度；00:30 触发
- **THEN** 整合前一日（昨天）的碎片

#### Scenario: 自定义时间
- **WHEN** 配置 `schedule: "0 1 * * *"`
- **THEN** 注册每天 01:00 的定时整合（仍整合前一日）

#### Scenario: 禁用定时
- **WHEN** 配置 `schedule: null` 或 `enabled: false`
- **THEN** 不注册定时任务，仅支持手动触发

### Requirement: 整合执行互斥
同一时刻 SHALL 只允许一个整合任务执行。运行中再触发 SHALL 返回"正在整合中"、不排队。此互斥与 MCS worker 线程串行化是两层（互斥锁防重入整合，worker 保线程安全）。

#### Scenario: 整合中再触发
- **WHEN** 整合正在执行，再收到整合请求
- **THEN** 返回 `{"ok": false, "status": "running", "message": "整合正在进行中"}`

#### Scenario: 整合完成后触发
- **WHEN** 上次整合已完成，收到新请求
- **THEN** 正常执行

### Requirement: 调度器生命周期
调度器 SHALL 随 `mcs_agent` 的 FastAPI app 启动而启动、随关闭而关闭（FastAPI lifespan 管理）。

#### Scenario: app 启动
- **WHEN** app 启动
- **THEN** APScheduler 启动，注册定时任务

#### Scenario: app 关闭
- **WHEN** app 关闭
- **THEN** APScheduler 优雅关闭，等当前任务完成

### Requirement: 整合完成日志
整合完成后 SHALL 记 INFO 日志（日期、事件数、耗时）；失败记 ERROR 并把状态置 `failed`。

#### Scenario: 成功
- **WHEN** 整合完成
- **THEN** 日志 `Consolidation done: date=2026-06-26, events=5, elapsed=12.5s`

#### Scenario: 失败
- **WHEN** 整合中出错
- **THEN** 记 ERROR，状态置 `failed`


## MODIFIED Requirements

### Requirement: 定时整合「昨天」
系统 SHALL 支持配置定时确认，默认 cron `30 0 * * *`（每天 00:30）确认**前一日**剩余的 `pending` 碎片（即兜底确认昨天用户未手动确认 / 未删除的碎片）。调度时间用 cron 表达式配置；定时作业的目标日期 SHALL 为「昨天」。

> 为何仍跑昨天而非当天：给当天用户手动逐条确认 / 删噪的窗口；夜间兜底处理前一天**幸存**的 `pending`（用户没主动处理的默认全部确认入图）。新模型不再单日锁定，因此跑当天不会产生孤儿，但跑昨天保留「人工先于自动」的把关顺序。

#### Scenario: 默认定时确认昨天 pending
- **WHEN** 系统启动，未配置自定义调度；00:30 触发
- **THEN** 确认前一日（昨天）剩余的 pending 碎片

#### Scenario: 自定义时间
- **WHEN** 配置 `schedule: "0 1 * * *"`
- **THEN** 注册每天 01:00 的定时确认（仍针对前一日）

#### Scenario: 禁用定时
- **WHEN** 配置 `schedule: null` 或 `enabled: false`
- **THEN** 不注册定时任务，仅支持手动触发

### Requirement: 整合完成日志
整合完成后 SHALL 记 INFO 日志（日期、`confirmed`/`skipped`/`failed`、耗时）；失败记 ERROR。

#### Scenario: 成功
- **WHEN** 整合完成
- **THEN** 日志含 `date`、`confirmed`、`skipped`、`failed`、`elapsed`

#### Scenario: 失败
- **WHEN** 整合中出错
- **THEN** 记 ERROR

## Why

现状碎片是「按天一个 MD 文件」，入图靠「按天 LLM 去噪 + 批量整合 + 单日 done 锁定」一锤子处理。用户无法在单条粒度上掌控「**哪条值得入图**」——随手记一条噪声、一句错记，要么被 LLM 默默丢弃（不可见、不可干预），要么整批进图后无法修正。

让记忆入图**可控、可审计、可修正**：每条随手记是独立可控的碎片，**确认才入图**，未确认可改可删；scheduler 次日把幸存的 pending 兜底确认。用户重新拿回「什么进我的记忆」的把关权。

## What Changes

- **BREAKING** 碎片从「按天 MD 文件」→「**结构化逐条记录**」（JSONL per day），每条碎片是一等对象 `{id, date, time, content, status, event_id}`。
- **三态状态机** `pending → confirming → confirmed`：`confirming` 中间态 + CAS 保证**并发确认不重复入图**（`ingest` 不幂等）。
- **确认即入图**：确认一条 `pending` 碎片 → 立即 `ingest_structured` → 锁 `confirmed`、挂 `event_id`。「每个碎片是一个事件」逐条落地。
- **碎片状态可见可控**：`pending` 可编辑 / 删除 / 确认；`confirming`/`confirmed` 只读。
- **移除去噪 LLM**（`Denoiser` / `LLMDenoiser` / `denoise.py`）：过滤改由用户删除不要的 `pending`，幸存的由 scheduler 全部确认。
- **整合管线语义改造**：`Consolidator` 从「读 MD → 去噪 → 批量 ingest」→「批量调 `confirm_one` 确认指定日期**剩余 pending**」。移除单日 `done` 锁定、移除「整合今天 warning」（增量幂等：已确认跳过、失败回退 pending）。
- **scheduler 兜底**：次日把**前一天剩余的 `pending`** 全部确认入图。**不暴露手动批量按钮**（最小改动；逐条确认 + scheduler 兜底已覆盖）。
- **日记改读结构化碎片**：当天全部碎片拼成文本 → LLM 概括。
- **`parse_fragments` 搬迁**：从 `consolidation.py` 移到 `fragments.py`（碎片层职责，消除碎片层反向依赖整合层）。
- **前端改造**：碎片块**分天展示** + 逐条确认、`confirmed` 只读；日历显示 `pending`/`confirmed` 计数；日记列表强化按天查看。
- **数据迁移**：现有 `fragments/*.md`（`HH:MM 内容` 行）→ 解析为 `pending` 碎片 JSONL。

## Capabilities

### New Capabilities
<!-- 无新增 capability——本次全部改造已有 capability -->

### Modified Capabilities
- `fragment-capture`: 碎片从「按天 MD」→「结构化逐条」；**三态状态机**（`pending`/`confirming`/`confirmed`）+ **纯文件层状态原语**（`begin_confirm`/`confirm_mark`/`abort_confirm`，不调 ingest）；逐条 `编辑`/`删除`（仅 pending）；`/note` 创建 `pending` 碎片返回 `id`。**守「捕获不碰 MCS」不变量**（确认即 ingest 的协调归 agent-consolidation）。
- `agent-consolidation`: **确认即 ingest 协调** `confirm_one`（`begin_confirm` CAS → `ingest` → `confirm_mark`，失败 `abort_confirm`）+ 单条确认端点 `POST /fragments/{id}/confirm` + **并发 CAS 不重复入图**；批量 `consolidate` 改调 `confirm_one`；移除去噪、移除单日锁定、移除 today warning、改增量幂等。
- `consolidation-scheduler`: 次日兜底确认**前一天剩余 `pending`**（替代旧的「整合昨天」）；目标态是「无遗留 `pending`」而非「单日 `done`」。
- `diary-generation`: 日记来源从「碎片 MD 全文」→「结构化碎片按时间拼接」（当天全量）。
- `memory-management-ui`: 碎片块分天展示 + 逐条确认交互 + `confirmed` 只读；日历显示 `pending`/`confirmed` 计数（**无批量按钮**）；日记列表强化按天查看。

## Impact

- **代码**：
  - `mcs_mem/fragments.py`：`FragmentStore` 重构（JSONL 存储 + 三态原语 + 逐条 CRUD）；`parse_fragments` **搬入**本模块；MD→JSONL 迁移 + 启动清理 `confirming` 残留。
  - `mcs_mem/consolidation.py`：`Consolidator` 重写（`confirm_one` + 批量 `consolidate`，移除 `Denoiser`）；`parse_fragments` 改 `from mcs_mem.fragments import`；`ConsolidationTracker` 降级为观测（移除单日锁定）。
  - `mcs_mem/diary.py`：`DiaryGenerator` 改读 `read_all`。
  - `mcs_mem/app.py`：路由改造（`/note` 返回 `id`；新增 `POST /fragments/{id}/confirm`；`PUT`/`DELETE` 仅 pending；`/fragments` 返回带状态列表）；**移除 today warning 逻辑**、移除旧整文件 `PUT` + `mtime` 乐观锁。
  - `mcs_mem/scheduler.py`：日志字段 `confirmed`/`skipped`/`failed`。
  - `mcs_mem/static/manage.html`：碎片块 + 日历 + 日记块前端改造（无批量按钮）。
  - `mcs_mem/prompts/denoise.py`：**移除**（去噪能力下线）。
- **数据兼容**：现有 `fragments/*.md` 需迁移为 JSONL（含 demo 数据 `mcs_mem_demo_data/fragments/`，`.md.migrated` 备份）。
- **API 兼容**：`/note`、`/fragments*`、`/consolidate*` 契约变更（**BREAKING**）。
- **测试**：`test_capture_api` / `test_consolidation` / `test_diary` / `test_manage_ui` 需配套改造，新增并发 CAS 测试。

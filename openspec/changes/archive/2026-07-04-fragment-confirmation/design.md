## Context

现状四层（`mcs_mem`）：

- **碎片捕获** `FragmentStore`：每天一个 `fragments/YYYY-MM-DD.md`，`/note` 追加 `HH:MM 内容` 行。纯文件 IO、保真、无状态。
- **整合** `Consolidator`：读当天 MD → `parse_fragments` 解析 → `Denoiser`（`LLMDenoiser` 逐条判去留）→ 逐条 `ingest_structured(content, ts)`。`ConsolidationTracker`（JSON）**单日 `done` 锁定**——再触发返回 `already`。
- **调度** `ConsolidationScheduler`：cron `30 0 * * *` 整合昨天。
- **日记** `DiaryGenerator`：读当天碎片 MD 全文 → LLM 概括。

问题：用户无法在**单条粒度**掌控「什么入图」——LLM 默默去噪（不可见、不可干预），整批入图后无法修正。需求要把「确认」这一关交回用户：每条碎片独立可控、确认才入图、scheduler 兜底。

约束（宪法）：不碰 MCS 图模型本身；`ingest_structured(content, timestamp)` 契约不变（一碎片一事件已满足）；不改 `mcs_agent` 前端；依赖方向 `mcs_mem → mcs_agent → mcs` 单向；**碎片捕获层不变量：捕获是文件 IO 旁路、不触碰 MCS**（这条决定了下面的 capability 切分）。

## Goals / Non-Goals

**Goals:**

- 碎片成为**有状态的一等对象**（结构化逐条），`pending → confirming → confirmed` 状态机。
- 确认即入图（一碎片一事件），`event_id` 可追溯；`confirmed` 锁死只读。
- `pending` 可编辑 / 删除；`confirming`/`confirmed` 只读。
- **并发确认不重复入图**（`ingest` 不幂等，靠 CAS 保证）。
- scheduler 次日兜底确认前一天剩余 `pending`（增量、幂等）。
- 日记改读结构化碎片（当天全量）。
- 现有 `fragments/*.md` 平滑迁移到 JSONL。

**Non-Goals:**

- 不做自动去噪 LLM（**移除** `Denoiser` / `LLMDenoiser` / `denoise.py`）——过滤靠用户删 `pending`。
- **不做手动「确认当天全部」按钮**——批量确认由 scheduler 兜底，前端不暴露批量入口（最小改动；用户逐条确认 + scheduler 兜底已覆盖）。
- 不做 `confirmed` 的编辑 / 删除 / 回退（已入图，锁死，删图超范围）。
- 不做事件 → 碎片的反向导航（仅碎片存 `event_id` 单向追溯）。
- 不改 `ingest_structured` 本身、不改图模型、不改 `mcs_agent` 前端。

## Decisions

### D1：capability 切分——碎片层状态 vs 整合层 ingest 协调

「确认」跨两层：文件层标 `confirmed`（`FragmentStore` 能做）+ 入图 `ingest`（要 `memory`，`FragmentStore` 不能做）。为守住「**捕获层不碰 MCS**」不变量，切分：

- **`fragment-capture`**（碎片层，纯文件 IO）：碎片对象 / 存储 / CRUD / **状态机原语**（`begin_confirm`/`confirm_mark`/`abort_confirm`，纯文件、内锁原子、不调 ingest）。`/note`、`GET/PUT/DELETE /fragments*` 属此层。
- **`agent-consolidation`**（整合层，碰 MCS）：**确认协调** `confirm_one(id)`（串联原语 + `ingest`）、单条确认端点 `POST /fragments/{id}/confirm` 的 ingest 行为、批量 `consolidate`、并发 CAS、失败重试。

端点路径 `/fragments/{id}/confirm` 只是 URL 名，语义归 agent-consolidation。依赖方向：整合层注入 `FragmentStore` + `memory`，碎片层不反向依赖整合层。

### D2：碎片存储 = JSONL per day

每天一个 `fragments/YYYY-MM-DD.jsonl`，每行一个碎片 JSON 对象：

```
{"id": "2026-06-28T14:30:00", "date": "2026-06-28", "time": "14:30",
 "content": "...", "status": "pending|confirming|confirmed", "event_id": null|"ev_3",
 "created_at": "2026-06-28T14:30:00"}
```

- **为何 JSONL 非 SQLite**：与现有「按天目录」模式一致、人类可读、追加友好、最小改动、易测试易迁移。
- **为何非 MD**：MD 无法自然表达 `id`/`status`/`event_id`/不可改；逐条 CRUD 在 MD 上要解析全文重写，别扭。
- **`id` 生成**：`{date}T{HH:MM:SS}`；`FragmentStore` 创建时保证当天唯一（同秒追加 `-2`/`-3`）。稳定、可测、可读。
- **并发**：`threading.Lock` 串行化碎片追加 / 改 / 删 / 状态原语（捕获纯文件 IO，不经 MCS worker）。

### D3：状态机 `pending → confirming → confirmed` + CAS（防并发重复入图）

`ingest` 不幂等（每次建新事件）。并发确认同一条、或 `confirm_one` 与 `consolidate` 撞，单纯「ingest 前 check status」有竞态 → 重复入图。**必须**用 `confirming` 中间态 CAS：

- `begin_confirm(id)`：文件锁内**原子** `pending → confirming`（CAS）。非 `pending`（已 `confirming`/`confirmed`）→ 抢占失败、返回（不 ingest）。**抢占成功者独占 ingest 权**。
- `ingest_structured` → `event_id`。
- `confirm_mark(id, event_id)`：`confirming → confirmed` + 存 `event_id`。
- `abort_confirm(id)`：`ingest` 失败时 `confirming → pending`（清占位，可重试），MUST NOT 留 `confirming` 悬空。

效果：并发请求只有一个 `begin_confirm` 成功 → 只 `ingest` 一次；其余抢占失败、幂等返回。`Consolidator._mutex`（防 consolidate-vs-consolidate）与 per-碎片 CAS（防 confirm-vs-confirm / confirm-vs-consolidate）是**两层互斥**。

### D4：确认协调 `confirm_one(id)` 住 `Consolidator`

`Consolidator` 已持有 `memory` + `fragment_store`，是放 `confirm_one` 的天然位置（单一方法、API + consolidate 复用）：

```
confirm_one(id):
  if not begin_confirm(id):          # CAS 抢占；已 confirming/confirmed → 幂等返回 already
      return already(碎片当前 status / event_id)
  try:
      event_id = memory.ingest_structured(content, ts)
      confirm_mark(id, event_id)     # confirming → confirmed
      return confirmed(event_id)
  except:
      abort_confirm(id)              # 回退 pending，可重试
      raise
```

`POST /fragments/{id}/confirm` 调 `confirm_one`；`consolidate(date)` 循环对每条 pending 调 `confirm_one`。`FragmentStore` 只暴露三个纯文件原语，**不碰 MCS**（守不变量）。

### D5：`Consolidator.consolidate` 重写——批量调 `confirm_one`

`consolidate(date)`：

1. 读当天**全部 `pending`** 碎片（`confirming`/`confirmed` 自然跳过 = 幂等）。
2. 逐条 `confirm_one`：成功计数 `confirmed`、失败（abort 回退）计数 `failed`、续跑（不中断不回滚）。
3. 返回 `{confirmed, skipped, failed, date}`。

- **移除** `Denoiser` / `LLMDenoiser`。
- **移除单日 `done` 锁定**：新模型当天还会新写 `pending`，「单日 done」不成立。`consolidate` 幂等可重入。
- **保留** `_mutex` 防同日并发整合。
- `ConsolidationTracker` **降级为观测**：记录每日期 `{date, last_run, confirmed, failed}`，**不再**因 `done` 拒重入。
- **移除**「整合今天 warning」（无锁定，今天后续 pending 仍可再整合）。

### D6：scheduler 兜底确认前一天剩余 `pending`

`ConsolidationScheduler._run_yesterday` 调 `consolidator.consolidate(昨天)`——语义自然对齐。日志记 `confirmed`/`skipped`/`failed`。cron / env / lifespan 不变。新模型不再单日锁定，跑当天也不会产生孤儿；仍跑昨天保留「人工先于自动」的把关顺序。

### D7：日记改读结构化碎片

`DiaryGenerator`：

- `FragmentStore.read_all(date)` 返回当天**全部**碎片（`pending`/`confirming`/`confirmed`，按 `time` 排序）。
- 拼成 `HH:MM 内容` 文本（与旧 MD 行格式一致）→ 复用现有 `_DIARY_PROMPT`（`{date}` 注入防杜撰日期 / 星期 / 天气）。
- 超窗分块合并（`_summarize_long`）不变。
- 全部碎片都进日记（Q4 选「当天全部碎片」）。

### D8：MD → JSONL 迁移（`parse_fragments` 搬到碎片层）

- `parse_fragments` **从 `consolidation.py` 搬到 `fragments.py`**（碎片文本→碎片对象是碎片层职责；消除碎片层反向依赖整合层）。`consolidation.py` 改 `from mcs_mem.fragments import parse_fragments`（符合现有依赖方向，无反向依赖）。
- `FragmentStore.__init__`：对每个有 `.md` 无 `.jsonl` 的日期，**幂等**一次性迁移（`parse_fragments` 解析 → 建 `pending` 碎片写 JSONL）。
- 迁移后 `.md` 重命名为 `.md.migrated`（**保留备份**，不丢数据）。
- demo 数据 `mcs_mem_demo_data/fragments/*.md` 同路径迁移。

### D9：API 契约改造（**BREAKING**）

| 端点 | 旧 | 新 |
|---|---|---|
| `POST /note` | 追加 MD 行 → `{ok,date,time}` | 创建 `pending` 碎片 → `{ok,id,date,time}` |
| `GET /fragments/{date}` | 当天 MD 全文 + mtime | 当天碎片列表 `[{id,time,content,status,event_id}]` |
| `POST /fragments/{id}/confirm` | —（新增） | 调 `confirm_one` → `{ok,id,status,event_id}` |
| `PUT /fragments/{id}` | 整文件覆盖（乐观锁） | 改单条 `content`；非 `pending` → 409 |
| `DELETE /fragments/{id}` | —（新增） | 删单条；非 `pending` → 409 |
| `POST /consolidate` | 去噪+批量 ingest + today warning | 确认指定日期剩余 `pending`；返回 `{confirmed,skipped,failed}`；**无 today warning** |
| `/consolidate/status(es)` | done/failed/running 锁定语义 | 降级为「最后整合结果」观测 |

旧「整文件 `PUT` + `mtime` 乐观锁」随 MD 模型一并移除。

### D10：前端 `manage.html` 改造（无批量按钮）

- **碎片块**：按日期分组（倒排）；`pending` 条目显示内容 + `[确认][编辑][删除]`、可内联编辑；`confirming`/`confirmed` 条目只读（✓ + `event_id`）。逐条确认调 `POST /fragments/{id}/confirm`。
- **日历**：每天显示 `pending`/`confirmed` 计数（替代旧整合状态色块）。**不暴露批量确认按钮**（批量由 scheduler 兜底）。
- **日记块**：侧栏按天列表强化（`/diaries` 倒排 + 点击载入）。
- 召回 / 图谱块不变。

## Risks / Trade-offs

- **[并发重复入图]** → CAS `confirming` 中间态必须（D3）；per-碎片 CAS + `_mutex` 两层互斥兜底。测试覆盖并发确认同一条。
- **[`begin_confirm` 后 `ingest` 前崩溃]**：碎片留 `confirming` 悬空。→ `abort_confirm` 在异常路径调用；进程重启若发现 `confirming` 残留，启动时清理回 `pending`（迁移/初始化时扫一遍）。
- **[BREAKING：数据格式 + API]** → JSONL 迁移幂等 + `.md.migrated` 备份；demo 数据同步；契约改动随测试覆盖。
- **[去噪下线 → 噪声全入图]**：用户不删的 `pending` scheduler 全确认。→ trade-off：**可控性优先于自动去噪**（用户明确选择）；前端给显眼删除入口。
- **[tracker 单日锁定移除]** → 测试覆盖幂等（重跑 / 并发不重复入图）；CAS + status 门控是安全网。

## Migration Plan

1. `parse_fragments` 搬到 `fragments.py`；`FragmentStore` 加 JSONL 存储 + 三态原语（`begin_confirm`/`confirm_mark`/`abort_confirm`）+ `.md→.jsonl` 迁移（幂等 + 备份 + 启动清理 `confirming` 残留）。
2. `/note` 改创建 `pending` 碎片（返回 `id`）。
3. `Consolidator.confirm_one` + `POST /fragments/{id}/confirm` + `PUT`/`DELETE`（仅 pending）。
4. `Consolidator.consolidate` 重写（循环 `confirm_one`，移除去噪 / 单日锁定 / today warning）；`tracker` 降级。
5. `scheduler` 对齐（日志字段）。
6. `DiaryGenerator` 改 `read_all`。
7. `manage.html` 前端改造（无批量按钮）。
8. demo 数据迁移 + 全套测试改造。

**回滚**：`.md.migrated` 备份在；旧代码分支可还原（数据未丢）。

## Open Questions

- **去噪移除**：已确认（用户选择「scheduler 兜底全确认」，去噪无位置）。如未来想要「兜底前去噪建议」，另开 change。
- **启动清理 `confirming` 残留**：实现时在 `FragmentStore.__init__` 扫残留 `confirming` → 回退 `pending`（防崩溃悬空），属合理健壮性默认。

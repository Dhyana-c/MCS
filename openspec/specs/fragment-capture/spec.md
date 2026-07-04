# fragment-capture Specification

## Purpose
TBD - created by archiving change personal-memory-system. Update Purpose after archive.
## Requirements
### Requirement: 碎片文件按日期归档
系统 SHALL 按日期创建 JSONL 碎片文件，文件名格式 `YYYY-MM-DD.jsonl`，存储在配置的碎片目录下（默认 `~/.mcs_memory/fragments/`）。每行一个碎片 JSON 对象（含 `id`/`date`/`time`/`content`/`status`/`event_id`）。

#### Scenario: 首次记录当日消息
- **WHEN** 用户在 2026-06-27 发送第一条消息，且当日 JSONL 不存在
- **THEN** 系统创建 `2026-06-27.jsonl`，并写入该碎片对象

#### Scenario: 当日文件已存在
- **WHEN** 用户在 2026-06-27 发送消息，且 `2026-06-27.jsonl` 已存在
- **THEN** 在文件末尾追加该碎片对象，不影响已有碎片

### Requirement: 碎片目录自动创建
系统 SHALL 在首次写入时自动创建碎片目录（含中间目录），不因目录不存在而报错。

#### Scenario: 目录不存在
- **WHEN** 配置的碎片目录不存在
- **THEN** 系统自动创建该目录及所有中间目录，然后正常写入

### Requirement: 碎片文件列表查询
系统 SHALL 提供 `GET /fragments` 端点，返回已有碎片文件列表（按日期倒排）。

#### Scenario: 列出碎片
- **WHEN** `GET /fragments`
- **THEN** 返回 `{"fragments": ["2026-06-27.md", "2026-06-26.md"]}`（按日期倒排）

#### Scenario: 无碎片文件
- **WHEN** 碎片目录为空
- **THEN** 返回 `{"fragments": []}`

### Requirement: 消息实时追加到当天碎片
每条 `/note` 消息 SHALL 在当天 JSONL 创建一条 `pending` 碎片（`time` 取服务器本地时间），SHALL NOT 触发任何 LLM / MCS 调用（纯文件 IO）。返回 SHALL 含碎片 `id`。

#### Scenario: 记录单条创建碎片
- **WHEN** 用户在 14:30 发送 "今天和团队讨论了新方案"
- **THEN** 当天 JSONL 追加一条 pending 碎片（time=14:30），返回其 id，且未发生 ingest / LLM 调用

#### Scenario: 连续记录多条
- **WHEN** 用户连续发送 "消息A"、"消息B"
- **THEN** 按顺序追加两条碎片，各带自己的时间戳与 id

### Requirement: pending 碎片可经 API 编辑、confirming/confirmed 只读
`pending` 碎片的 `content` SHALL 可经 API 编辑、可删除；`confirming` / `confirmed` 碎片 SHALL 只读（不可编辑、不可删除）。系统读取 SHALL 返回碎片当前内容（不缓存旧版本）。

#### Scenario: 编辑 pending 碎片后读取到新内容
- **WHEN** 用户编辑一条 pending 碎片的 content 并保存
- **THEN** 下次读取得到修正后的 content

#### Scenario: confirming / confirmed 碎片不可改
- **WHEN** 尝试编辑 / 删除一条 confirming 或 confirmed 碎片
- **THEN** 返回 409，碎片内容不变

### Requirement: 经 API 编辑单条碎片
系统 SHALL 提供 `PUT /fragments/{id}` 编辑单条碎片 `content`，**仅 `pending` 可改**；`confirming` / `confirmed` SHALL 返回 409。不存在该 id 的碎片 SHALL 返回 404。

#### Scenario: 编辑 pending 碎片
- **WHEN** `PUT /fragments/{id}`，body `{"content": "修正后的内容"}`，该碎片 pending
- **THEN** 更新该碎片 content，返回 `{ok:true, id}`

#### Scenario: 拒改非 pending 碎片
- **WHEN** `PUT /fragments/{id}`，该碎片 confirming 或 confirmed
- **THEN** 返回 409，碎片内容不变

### Requirement: 记录消息 API 返回碎片 id
系统 SHALL 提供 `POST /note` 端点，接受用户消息并在当天 JSONL 创建一条 pending 碎片。该端点 SHALL 挂在 `mcs_mem` 的 FastAPI app 上。

#### Scenario: 正常记录
- **WHEN** `POST /note`，body `{"content": "今天完成了设计文档"}`
- **THEN** 返回 `{"ok": true, "id": "...", "date": "2026-06-27", "time": "14:30"}`，碎片已创建（pending）

#### Scenario: 空消息拒绝
- **WHEN** `POST /note`，body `{"content": ""}` 或仅空白
- **THEN** 返回 HTTP 422，提示内容不能为空，且不创建碎片

### Requirement: 读取碎片返回带状态列表
系统 SHALL 提供 `GET /fragments/{date}` 端点，返回指定日期的全部碎片列表（含 `id`/`time`/`content`/`status`/`event_id`），`pending`/`confirming`/`confirmed` 都返回、按 `time` 排序。

#### Scenario: 读取已有
- **WHEN** `GET /fragments/2026-06-27`
- **THEN** 返回 `{"date": "2026-06-27", "fragments": [{id,time,content,status,event_id}, ...]}`（各态混列）

#### Scenario: 读取不存在
- **WHEN** `GET /fragments/2026-06-25`，该日无文件
- **THEN** 返回 HTTP 404

### Requirement: 捕获端点经 mcs_mem app 暴露
捕获相关端点（`/note`、`/fragments`、`/fragments/{date}`、`PUT /fragments/{id}`、`DELETE /fragments/{id}`）SHALL 注册到 `mcs_mem` 的 FastAPI app（`mcs_mem.create_app`，复用 `mcs_agent.register_base_routes`），与 `/chat` / `/graph/expand` 同居一 app、共用一端口；SHALL NOT 新建独立 app / 独立端口。注：`POST /fragments/{id}/confirm` 涉及 `ingest`（碰 MCS），其端点契约由 agent-consolidation 规定、同挂本 app。

#### Scenario: 与既有路由同居
- **WHEN** 启动 `mcs_mem` 的 app
- **THEN** `/chat`、`/note`、`/fragments` 等 MUST 在同一 app 实例、同一端口可达

#### Scenario: 捕获不依赖 agent / MCS 即可工作
- **WHEN** app 以一个无 `memory` 的 fake agent 构建（仅测试捕获）
- **THEN** `/note`、`/fragments`、`PUT/DELETE /fragments/{id}` MUST 仍正常工作（捕获 / 状态标记是文件 IO 旁路，不触碰 MCS）

### Requirement: 碎片为有状态一等对象
系统 SHALL 把每条碎片存储为独立、有状态的对象，每条含 `id`、`date`、`time`、`content`、`status`、`event_id`。`status` SHALL 为 `pending`（默认）/ `confirming` / `confirmed`。`event_id` 在 `pending`/`confirming` 时 SHALL 为 `null`，确认入图后 SHALL 记录关联事件 id。碎片 `id` SHALL 在全碎片空间唯一（默认 `{date}T{HH:MM:SS}`，同秒冲突追加 `-N`）。

#### Scenario: 随手记创建 pending 碎片
- **WHEN** 用户经 `/note` 记一条
- **THEN** 创建一条 `status=pending`、`event_id=null` 的碎片，返回其 `id`

#### Scenario: 确认后状态与事件 id 落定
- **WHEN** 一条 pending 碎片经确认协调（见 agent-consolidation）完成入图
- **THEN** 其 `status` 变 `confirmed`、`event_id` 为返回的事件 id

### Requirement: 碎片状态机（pending → confirming → confirmed）
碎片 `status` SHALL 单向流转 `pending → confirming → confirmed`：

- `pending`：可编辑 `content`、可删除、可发起确认（`begin_confirm`）。
- `confirming`：确认进行中（`ingest` 未落定）；SHALL 不可编辑、不可删除、不可重复发起确认（防并发改 / 并发重复入图）。
- `confirmed`：只读，挂 `event_id`；不可编辑、不可删除、不可回退（已入图）。

状态标记 SHALL 为**纯文件层原语**（`FragmentStore` 内 `threading.Lock` 保证原子），SHALL NOT 调 `ingest` / MCS——捕获层不触碰 MCS 的不变量保持（`ingest` 协调归 agent-consolidation）。

#### Scenario: pending → confirming（抢占）
- **WHEN** 对一条 pending 碎片发起确认
- **THEN** 经 `begin_confirm` 原子置 `confirming`

#### Scenario: confirming → confirmed（落定）
- **WHEN** 确认协调的 `ingest` 成功
- **THEN** 经 `confirm_mark` 置 `confirmed` + 存 `event_id`

#### Scenario: confirming → pending（回退）
- **WHEN** 确认协调的 `ingest` 失败
- **THEN** 经 `abort_confirm` 回退 `pending`（可重试）

#### Scenario: confirmed 不可回退
- **WHEN** 一条碎片已 confirmed
- **THEN** 任何状态回退 / 编辑 / 删除 SHALL 被拒

### Requirement: 碎片状态标记原语（纯文件层）
`FragmentStore` SHALL 提供三个**纯文件层**状态原语（不调 `ingest` / MCS，由内部锁保证原子）：

- `begin_confirm(id)`：原子 CAS `pending → confirming`；碎片非 `pending`（已 `confirming`/`confirmed`）SHALL 返回失败（抢占失败 / 已确认）。
- `confirm_mark(id, event_id)`：`confirming → confirmed` 并写入 `event_id`。
- `abort_confirm(id)`：`confirming → pending`（清空 `event_id` 占位，供 `ingest` 失败回退）。

`ingest` 协调（`begin_confirm → ingest → confirm_mark`，失败 `abort_confirm`）由 agent-consolidation 负责；本层只提供状态原语。

#### Scenario: begin_confirm 抢占成功
- **WHEN** `begin_confirm(id)`，碎片为 pending
- **THEN** 置 confirming、返回成功

#### Scenario: begin_confirm 已 confirming 抢占失败
- **WHEN** `begin_confirm(id)`，碎片已 confirming
- **THEN** 返回失败（不重复抢占），状态不变

#### Scenario: begin_confirm 已 confirmed 失败
- **WHEN** `begin_confirm(id)`，碎片已 confirmed
- **THEN** 返回失败（已确认），状态不变

#### Scenario: confirm_mark 落定
- **WHEN** `confirm_mark(id, event_id)`，碎片为 confirming
- **THEN** 置 confirmed、存 event_id

#### Scenario: abort_confirm 回退
- **WHEN** `abort_confirm(id)`，碎片为 confirming
- **THEN** 回退 pending、event_id 保持 null

### Requirement: 删除碎片 API
系统 SHALL 提供 `DELETE /fragments/{id}`：删除单条 **pending** 碎片。`confirming` / `confirmed` 碎片 SHALL 拒绝删除（返回 409）。

#### Scenario: 删除 pending 碎片
- **WHEN** `DELETE /fragments/{id}`，该碎片 pending
- **THEN** 删除该碎片，返回 `{ok:true, id}`

#### Scenario: 拒删 confirming / confirmed 碎片
- **WHEN** `DELETE /fragments/{id}`，该碎片 confirming 或 confirmed
- **THEN** 返回 409，碎片保留

### Requirement: 旧 MD 碎片迁移到 JSONL
系统 SHALL 在 `FragmentStore` 初始化时，对每个有 `.md` 无 `.jsonl` 的日期做**幂等**一次性迁移：解析 `HH:MM 内容` 行（经 `parse_fragments`，该函数属碎片层、位于 `mcs_mem/fragments.py`）→ 建 `pending` 碎片写 JSONL。迁移后 SHALL 把原 `.md` 重命名为 `.md.migrated`（保留备份、不丢数据）。已有 `.jsonl` 的日期 SHALL 跳过（不重复迁移）。

#### Scenario: 首次初始化迁移旧 MD
- **WHEN** 碎片目录有 `2026-06-20.md`、无 `2026-06-20.jsonl`，FragmentStore 初始化
- **THEN** 解析该 MD 为 pending 碎片写入 `2026-06-20.jsonl`，`.md` 重命名为 `.md.migrated`

#### Scenario: 已有 JSONL 不重复迁移
- **WHEN** 某日已有 `.jsonl`（含 `.md.migrated` 备份）
- **THEN** 跳过迁移，保留现状


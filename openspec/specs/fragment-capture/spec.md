# fragment-capture Specification

## Purpose
TBD - created by archiving change personal-memory-system. Update Purpose after archive.
## Requirements
### Requirement: 碎片文件按日期归档
系统 SHALL 按日期创建 Markdown 碎片文件，文件名格式 `YYYY-MM-DD.md`，存储在配置的碎片目录下（默认 `~/.mcs_memory/fragments/`）。

#### Scenario: 首次记录当日消息
- **WHEN** 用户在 2026-06-27 发送第一条消息，且当日 MD 文件不存在
- **THEN** 系统创建 `2026-06-27.md`，并追加该消息

#### Scenario: 当日文件已存在
- **WHEN** 用户在 2026-06-27 发送消息，且 `2026-06-27.md` 已存在
- **THEN** 系统在文件末尾追加，不覆盖已有内容

### Requirement: 消息实时追加到当天 MD
每条消息 SHALL 以 `HH:MM 内容` 格式追加到当天 MD 文件末尾，时间戳取服务器本地时间。追加 SHALL NOT 触发任何 LLM / MCS 调用（纯文件 IO）。

#### Scenario: 追加单条消息
- **WHEN** 用户在 14:30 发送 "今天和团队讨论了新方案"
- **THEN** 当天 MD 末尾追加一行 `14:30 今天和团队讨论了新方案`，且未发生 ingest / LLM 调用

#### Scenario: 连续追加多条
- **WHEN** 用户连续发送 "消息A"、"消息B"
- **THEN** 按顺序追加两行，各带自己的时间戳

### Requirement: 碎片目录自动创建
系统 SHALL 在首次写入时自动创建碎片目录（含中间目录），不因目录不存在而报错。

#### Scenario: 目录不存在
- **WHEN** 配置的碎片目录不存在
- **THEN** 系统自动创建该目录及所有中间目录，然后正常写入

### Requirement: 碎片文件可人工编辑且不缓存旧版本
碎片文件 SHALL 是纯文本 Markdown，用户可用编辑器直接打开修改。系统读取时 SHALL 返回文件当前内容（含手改），不缓存旧版本。

#### Scenario: 用户手动修正后读取到新内容
- **WHEN** 用户在编辑器中把某行内容改了
- **THEN** 下次读取 / 列表读到的是修正后的版本

### Requirement: 经 API 编辑当天碎片
系统 SHALL 提供 `PUT /fragments/{date}` 端点，以请求体整体覆盖指定日期的碎片文件，供管理 UI 内编辑。

#### Scenario: 网页内保存编辑
- **WHEN** 发送 `PUT /fragments/2026-06-27`，body 为 `{"content": "14:30 修正后的内容\n15:00 另一条"}`
- **THEN** `2026-06-27.md` 被整体覆盖为该内容，返回 `{"ok": true, "date": "2026-06-27"}`

#### Scenario: 编辑不存在的日期则创建
- **WHEN** `PUT /fragments/2026-06-20`，该日原无文件
- **THEN** 创建该文件并写入内容（自动建目录）

### Requirement: 碎片编辑乐观锁（防覆盖丢行）

`GET /fragments/{date}` 响应 SHALL 含文件 `mtime`。`PUT /fragments/{date}` 接受可选 `expected_mtime`：
若给定且与文件当前 mtime 不符（载入后被 `/note` 追加等改动），SHALL 返回 `409`（版本冲突）、
MUST NOT 覆盖。未带 `expected_mtime` 则不校验（向后兼容）。编辑器契约：先 `GET`（含 mtime）→ 编辑 →
`PUT`（带 `expected_mtime`）。

#### Scenario: 载入后被追加，PUT 检测冲突返回 409
- **WHEN** 编辑器 `GET /fragments/{date}` 得 mtime=T1，期间 `/note` 追加致 mtime 变 T2，编辑器 `PUT` 带 `expected_mtime=T1`
- **THEN** 返回 `409`，文件 MUST NOT 被覆盖（保留 T2 的新内容）

#### Scenario: 未带 expected_mtime 不校验
- **WHEN** `PUT /fragments/{date}` 不带 `expected_mtime`
- **THEN** 直接覆盖（向后兼容，不校验 mtime）

### Requirement: 记录消息 API
系统 SHALL 提供 `POST /note` 端点，接受用户消息并追加到当天碎片文件。该端点 SHALL 挂在 `mcs_agent` 的 FastAPI app 上。

#### Scenario: 正常记录
- **WHEN** `POST /note`，body `{"content": "今天完成了设计文档"}`
- **THEN** 返回 `{"ok": true, "date": "2026-06-27", "time": "14:30"}`，消息已追加

#### Scenario: 空消息拒绝
- **WHEN** `POST /note`，body `{"content": ""}` 或仅空白
- **THEN** 返回 HTTP 422，提示内容不能为空，且不写文件

### Requirement: 碎片文件列表查询
系统 SHALL 提供 `GET /fragments` 端点，返回已有碎片文件列表（按日期倒排）。

#### Scenario: 列出碎片
- **WHEN** `GET /fragments`
- **THEN** 返回 `{"fragments": ["2026-06-27.md", "2026-06-26.md"]}`（按日期倒排）

#### Scenario: 无碎片文件
- **WHEN** 碎片目录为空
- **THEN** 返回 `{"fragments": []}`

### Requirement: 读取碎片内容 API
系统 SHALL 提供 `GET /fragments/{date}` 端点，返回指定日期的碎片内容。

#### Scenario: 读取已有
- **WHEN** `GET /fragments/2026-06-27`
- **THEN** 返回 `{"date": "2026-06-27", "content": "14:30 今天完成了设计文档\n..."}`

#### Scenario: 读取不存在
- **WHEN** `GET /fragments/2026-06-25`，该日无文件
- **THEN** 返回 HTTP 404

### Requirement: 捕获端点经 mcs_agent app 暴露
捕获相关端点（`/note`、`/fragments`、`/fragments/{date}`、`PUT /fragments/{date}`）SHALL 注册到 `mcs_agent` 现有 FastAPI app（`create_app`），与 `/chat` / `/graph/expand` 同居一 app、共用一端口；SHALL NOT 新建独立 app / 独立端口。

#### Scenario: 与既有路由同居
- **WHEN** 启动 `mcs_agent` 的 app
- **THEN** `/chat`、`/note`、`/fragments` 等 MUST 在同一 app 实例、同一端口可达

#### Scenario: 捕获不依赖 agent / MCS 即可工作
- **WHEN** app 以一个无 `memory` 的 fake agent 构建（仅测试捕获）
- **THEN** `/note`、`/fragments` MUST 仍正常工作（捕获是文件 IO 旁路，不触碰 MCS）


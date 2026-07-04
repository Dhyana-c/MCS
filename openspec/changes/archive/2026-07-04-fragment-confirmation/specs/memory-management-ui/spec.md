## MODIFIED Requirements

### Requirement: 管理看板静态页
系统 SHALL 在 `mcs_mem/static` 提供一张管理看板页（`manage.html`），经 `mcs_mem.create_app` 挂载可达，纯 HTML/JS、无构建步骤。`/` SHALL 返回 `manage.html`（主入口）。页面 SHALL 含：记录、碎片、整合、日记、召回、图谱六块。

#### Scenario: 页面可达
- **WHEN** 访问 `/` 或 `/manage.html`
- **THEN** 返回管理看板页，六块区域均渲染

### Requirement: 碎片列表与网页内编辑块
看板 SHALL 按日期分组（倒排）列出碎片（`GET /fragments`），每组 `GET /fragments/{date}` 载入该日碎片（`pending`+`confirmed` 混列、带状态）。`pending` 碎片 SHALL 显示「确认 / 编辑 / 删除」入口；`confirmed` 碎片 SHALL 只读（标 ✓、显示 `event_id`、无编辑 / 删除 / 确认入口）。确认调 `POST /fragments/{id}/confirm`，编辑调 `PUT /fragments/{id}`，删除调 `DELETE /fragments/{id}`。

#### Scenario: 分天展示两态
- **WHEN** 打开碎片块
- **THEN** 按日期分组列出碎片，pending 与 confirmed 分别标识

#### Scenario: 逐条确认
- **WHEN** 对一条 pending 碎片点"确认"
- **THEN** 调 `POST /fragments/{id}/confirm`，成功后该条转只读 confirmed

#### Scenario: confirmed 只读
- **WHEN** 一条碎片已 confirmed
- **THEN** 不显示编辑 / 删除 / 确认入口（只读、显示 event_id）

#### Scenario: 编辑 / 删除 pending
- **WHEN** 对一条 pending 碎片编辑或删除
- **THEN** 调 `PUT`/`DELETE /fragments/{id}`，成功后刷新列表

### Requirement: 整合块（日历 + 触发 + 状态）
看板 SHALL 用 `GET /consolidate/statuses` 渲染日历总览（每日显示 `pending`/`confirmed` 计数）。看板 SHALL NOT 暴露批量确认按钮——批量确认由 scheduler 兜底，前端仅做逐条确认（碎片块）+ 日历观测；`POST /consolidate` 端点保留供 scheduler / API 调用。

#### Scenario: 日历总览
- **WHEN** 打开整合块
- **THEN** 调 `GET /consolidate/statuses`，按每日 pending/confirmed 计数渲染

#### Scenario: 无批量按钮
- **WHEN** 打开看板
- **THEN** 整合块无「确认当天全部」按钮（仅日历观测 + 逐条确认入口）

### Requirement: 日记块
看板 SHALL 支持生成日记（`POST /diary`）、查看（`GET /diary/{date}`）、并**强化按天列表查看**（`GET /diaries` 侧栏按天倒排、点击载入该日日记）。

#### Scenario: 列表按天查看
- **WHEN** 打开日记块
- **THEN** 侧栏列出已生成日记（按日倒排），点击某日载入该日日记内容

#### Scenario: 生成并查看
- **WHEN** 选某日点"生成日记"
- **THEN** 调 `POST /diary`，成功后 `GET /diary/{date}` 展示日记内容；当天无碎片则提示 no_fragments

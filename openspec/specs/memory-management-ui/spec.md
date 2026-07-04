# memory-management-ui Specification

## Purpose
TBD - created by archiving change memory-management-ui. Update Purpose after archive.
## Requirements
### Requirement: 管理看板静态页
系统 SHALL 在 `mcs_mem/static` 提供一张管理看板页（`manage.html`），经 `mcs_mem.create_app` 挂载可达，纯 HTML/JS、无构建步骤。`/` SHALL 返回 `manage.html`（主入口）。页面 SHALL 含：记录、碎片、整合、日记、召回、图谱六块。

#### Scenario: 页面可达
- **WHEN** 访问 `/` 或 `/manage.html`
- **THEN** 返回管理看板页，六块区域均渲染

### Requirement: 记录块
看板 SHALL 提供记录输入，提交时 `POST /note`，成功后清空输入并提示已记录（日期 + 时间）。

#### Scenario: 记录一条
- **WHEN** 在记录框输入内容并提交
- **THEN** 调 `POST /note`，成功后提示 `已记录 (date time)`，输入清空

#### Scenario: 空内容
- **WHEN** 提交空 / 纯空白
- **THEN** 前端拦截或后端 422，提示内容不能为空，不发无效记录

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

### Requirement: 召回块（只读 ReAct，独立端点）
看板的召回 SHALL 走新增的 `POST /recall` 端点，由一个**只读 agent 实例**（用 `ToolsetConfig(enabled=READONLY_TOOL_NAMES)` 构造——工具集由 `ToolSpec.readonly` 元数据**白名单**驱动、非 `if name != "learn"` 黑名单；与主 chat agent 共用同一 `MemoryStore`）跑 ReAct 并渲染回复。召回 MUST NOT 写图。SHALL NOT 在 UI 层另造检索逻辑。**新增写图工具 MUST 标 `ToolSpec(readonly=False)`**，使其自动排除出只读集——否则会被静默放进召回、破坏"MUST NOT 写图"。

#### Scenario: 召回提问只读
- **WHEN** 在召回框输入问题并提交
- **THEN** 以禁用 `learn` 的工具集跑 ReAct 并渲染回复
- **AND** 该次召回 MUST NOT 产生任何写图（无新事件 / 概念）

#### Scenario: 召回不触发 learn
- **WHEN** 召回问题措辞像陈述（可能诱使 agent 调 learn）
- **THEN** 因 `learn` 不在只读工具集，MUST NOT 写图

#### Scenario: 只读集由 readonly 元数据白名单驱动
- **WHEN** 检查 `READONLY_TOOL_NAMES`（只读工具白名单）
- **THEN** MUST 仅含 `readonly=True` 的工具（search / associate / reason / recall / generalize / arbitrate）
- **AND** MUST NOT 含 `learn`（唯一 `readonly=False`）
- **AND** 未来新增 `readonly=False` 的写图工具 MUST 自动不进只读集（白名单机制，非黑名单 `if name != "learn"`）

### Requirement: 嵌入图谱（依赖既有 graph-visualization，不拥有其修复）
看板 SHALL 在 `manage.html` 嵌入图谱视图（iframe 复用 `graph.html` 或共用组件），消费现有 `GET /graph/expand`。本片 SHALL NOT 重新定义图谱渲染契约（已由 `graph-visualization` spec 规定）、SHALL NOT 拥有 `graph.html` 与统一模型对齐的代码修复（该修复由独立 change `graph-renderer-align` 负责，不属本片 scope）。本片对图谱的责任仅为**嵌入 + 消费**，并以 graph.html 已对齐统一模型为前置依赖。

#### Scenario: 嵌入渲染根视图
- **WHEN** graph.html 已对齐统一模型，图谱块打开拉 `/graph/expand?node_id=__seed_root__`
- **THEN** 图谱在看板内可见并按 `graph-visualization` spec 渲染

#### Scenario: graph.html 未对齐时降级
- **WHEN** graph.html 对齐任务尚未落地（仍渲染异常）
- **THEN** 图谱块按"缺块降级"灰显 + 提示，MUST NOT 阻塞看板其余五块


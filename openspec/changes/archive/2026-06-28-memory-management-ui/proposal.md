> ⚠️ **架构修订（change [`mcs-mem-package-extract`](../mcs-mem-package-extract/proposal.md)）**：
> 本 change 原 design「`mcs_agent/static/manage.html`、端点挂 `mcs_agent` app」已被推翻——
> 管理看板 + `/recall` 端点现位于独立 `mcs_mem` 包（`mcs_mem/static/manage.html`、
> `mcs_mem/app.py`），经 `mcs_mem.create_app` 挂同一 app（单向依赖 `mcs_mem` → `mcs_agent` →
> `mcs`）。下文「`mcs_agent/static`」「挂 `mcs_agent` app」应据此理解为 `mcs_mem`。

## Why

前三片把后端补齐了（捕获 / 整合 / 日记），但全得靠 curl 调 API。用户要一个**前端页面来管理整个个人记忆系统**：随手记、改碎片、看整合状态、读日记、召回、看图谱——一站式。

UI 全挂在 `mcs_agent/static`（复用现有 `StaticFiles` 挂载），纯 HTML/JS、零构建步骤，与现有聊天页 / 图谱页同居。

## What Changes

- 新增 **管理看板（memory-management-ui）**：`mcs_agent/static` 一张管理页，六块：
  1. **记录** → `POST /note`（Slice 1）
  2. **碎片列表 + 网页内编辑** → `GET /fragments`、`GET/PUT /fragments/{date}`（Slice 1）
  3. **整合**：日历总览（哪些天 done/pending/failed）+ 单日触发 + 状态 → `GET /consolidate/statuses`、`POST /consolidate`、`GET /consolidate/status`（Slice 2）
  4. **日记**：生成 + 查看 → `POST /diary`、`GET /diary/{date}`、`GET /diaries`（Slice 3）
  5. **召回** → 新增 `POST /recall`：**只读 ReAct**（用 `ToolsetConfig` 构只读 agent 实例、禁 `learn` 工具——召回不该写图），与主 chat 共用同一 `MemoryStore`（见 design D2）
  6. **嵌入图谱** → `GET /graph/expand`（已有端点）
- **嵌入图谱**（不拥有 graph.html 修复）：`graph.html` 当前代码读旧字段（`role`/`kind`/`label`）、偏离既有 `graph-visualization` spec——该代码债由**独立 change [`graph-renderer-align`](../graph-renderer-align/proposal.md)** 修复（对齐 `node_class`/`type`），**不属本片 scope**。本片只**依赖** graph.html 已对齐，把它嵌入看板（iframe / 共用组件）

## Capabilities

### New Capabilities

- `memory-management-ui`: 个人记忆管理看板——记录 / 碎片编辑 / 整合日历 + 触发 / 日记 / 召回 / 嵌入图谱，静态页挂 `mcs_agent/static`

### Modified Capabilities

（无 spec 级修改，也无 graph-visualization 代码改动——graph.html 对齐既有 spec 由独立 change `graph-renderer-align` 负责、不属本片；本片只新增 `memory-management-ui` capability + `POST /recall` 端点）

## Impact

- **依赖 Slice 1/2/3**：消费其全部 API
- **召回 = 只读 ReAct**：新增 `POST /recall`，用现成 `ToolsetConfig(enabled=只读工具集)` 构一个禁 `learn` 的只读 agent 实例（与主 chat agent 共用 `MemoryStore`），复用既有 builder 机制、零侵入 loop（见 design D2）
- **改 `mcs_mem/static`**：新增管理页 `manage.html`（含召回 `POST /recall` 端点）；**不**改 `graph.html`（其对齐由 `graph-renderer-align` 负责）
- **依赖 graph.html 已对齐**：本片嵌入图谱要求 graph.html 已按统一模型渲染——该对齐由独立 change `graph-renderer-align` 负责（见 design D3），本片不拥有
- **不改后端 graph_view / 不改 graph-visualization spec**：后端与 spec 都已在统一模型上（[graph-visualization spec:92](../../specs/graph-visualization/spec.md)）

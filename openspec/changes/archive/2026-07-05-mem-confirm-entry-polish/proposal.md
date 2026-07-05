## Why

现有看板把"碎片保存 → 入图"做得不顺：

1. **note 成功后无即时确认路径**——「记录」成功只提示「已记录 (time)」，要入图得自己去「收件箱」找到刚记的那条、再点「确认」（2 跳）。
2. **「确认」一键即入图、且 `confirmed` 不可撤销**（只读、挂 `event_id`），但前端无任何防误——误点即把噪音永久写进图。

本次打磨这条路径：note 成功给**即时单条确认**入口（缩 2 跳为 1 跳，可忽略）、确认操作加**轻量二次确认**防误。

> **明确 Non-goal**：不碰 `memory-management-ui` spec 的「整合块 SHALL NOT 暴露批量确认按钮」约束（[spec:44](../../specs/memory-management-ui/spec.md)）——批量确认仍交 scheduler 次日 00:30 兜底，保留 pending 去噪缓冲。这与「图谱是 mem_agent 次要后台能力」的定位一致。

## What Changes

- **C · note 后即时单条确认**：「今日」视图记录成功反馈 SHALL 多提供一个「立即确认入图」入口，指向刚创建的碎片 id（`POST /note` 已返回 `id`），点击调 `POST /fragments/{id}/confirm`。可忽略——用户不点则碎片仍 `pending`（去收件箱逐条确认 / scheduler 兜底，行为不变）。
- **D · 确认操作二次确认防误**：所有触发「确认入图」的地方（收件箱逐条「确认」、C 新增的即时确认）SHALL 在调用 `/confirm` 前加轻量二次确认；`confirmed` 不可撤销，防误点。
- **纯前端**：仅改 `mcs_mem/static/manage.html`，调既有 API；不改后端契约、不改三态状态机、不改 scheduler、不碰 MCS 核心。

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

- `memory-management-ui`: 增强两处 requirement——①「记录块」成功反馈增加指向新碎片的即时确认入口；②「逐条确认」scenario 增加二次确认防误（`confirmed` 不可撤销）。**不**改「整合块 SHALL NOT 批量确认」约束。

## Impact

- **改 `mcs_mem/static/manage.html`**：今日视图 `note` 成功分支（即时确认入口，落专用受管容器 `#note-confirm`）+ `renderFragment` 确认按钮 + `confirmFragment`（二次确认）。
- **不改后端**：`/note`、`/fragments/{id}/confirm` 契约不变；`Consolidator` / `FragmentStore` / 三态状态机不动。
- **不改 `memory-management-ui` spec 的整合块约束**（保留 SHALL NOT 批量）。
- **测试**：`tests/test_manage_ui.py` 加结构断言（manage.html 含即时确认入口 hook + 二次确认标记，防回归误删）。前端 JS 交互的端到端行为（点击 → 调 API → 刷新）无 pytest 覆盖——项目无浏览器自动化依赖、本次不引入，靠结构断言 + 手动验证兜底。

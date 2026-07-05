## MODIFIED Requirements

### Requirement: 记录块
看板 SHALL 提供记录输入，提交时 `POST /note`，成功后清空输入、提示已记录（日期 + 时间），**并在反馈处提供一个「立即确认入图」入口**——指向刚创建的碎片 id（`POST /note` 返回的 `id`），点击经二次确认后调 `POST /fragments/{id}/confirm`。该入口 SHALL 可忽略：用户不点则碎片仍 `pending`（行为与去收件箱逐条确认一致，仍可由 scheduler 兜底）。

#### Scenario: 记录一条
- **WHEN** 在记录框输入内容并提交
- **THEN** 调 `POST /note`，成功后提示 `已记录 (date time)`、输入清空，并在反馈处显示指向该新碎片的「立即确认入图」入口

#### Scenario: 空内容
- **WHEN** 提交空 / 纯空白
- **THEN** 前端拦截或后端 422，提示内容不能为空，不发无效记录

#### Scenario: 即时确认可忽略
- **WHEN** 记录成功后不点「立即确认入图」（如再记一条 / 离开页面）
- **THEN** 碎片保持 `pending`，不调 `/confirm`；后续可在收件箱逐条确认或由 scheduler 兜底

## ADDED Requirements

### Requirement: 确认入图防误
看板所有触发「确认入图」的入口（收件箱逐条「确认」、记录块的「立即确认入图」）SHALL 在调用 `POST /fragments/{id}/confirm` 前加一次轻量二次确认（如原生 `confirm()` 或 inline 二次确认控件）。理由：`confirmed` 不可撤销（只读、挂 `event_id`、已写入图谱事件），防误点把噪音永久入图。二次确认逻辑 SHALL 在确认入口的单点（`confirmFragment`）收口，使所有调用方一致获得防误。

#### Scenario: 逐条确认二次确认
- **WHEN** 在收件箱对一条 pending 碎片点「确认」
- **THEN** 先弹二次确认；用户确认后才调 `POST /fragments/{id}/confirm`、成功后转只读 confirmed；用户取消则不调、碎片留 pending

#### Scenario: 即时确认二次确认
- **WHEN** 记录成功后点「立即确认入图」
- **THEN** 先弹二次确认；用户确认后才调 `POST /fragments/{id}/confirm`；取消则不调（碎片留 pending）

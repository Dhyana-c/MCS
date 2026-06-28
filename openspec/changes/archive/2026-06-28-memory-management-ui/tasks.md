## 1. 看板骨架

- [ ] 1.1 新增 `mcs_agent/static/manage.html`：六块布局（记录 / 碎片 / 整合 / 日记 / 召回 / 图谱），原生 HTML/CSS/JS，无构建
- [ ] 1.2 顶部导航与现有 `index.html`（聊天）/ `graph.html`（图谱）互链
- [ ] 1.3 缺块降级：依赖的后端片未就绪时对应块灰显 + 提示（前端容错，不报错）

## 2. 记录块

- [ ] 2.1 输入框 + 提交 → `POST /note`；空内容前端拦截；成功提示 `已记录 (date time)` + 清空

## 3. 碎片编辑块

- [ ] 3.1 列表 `GET /fragments`（按日倒排）
- [ ] 3.2 选日 `GET /fragments/{date}` 载入 textarea
- [ ] 3.3 保存 `PUT /fragments/{date}`（整文件覆盖）；契约：先 GET 全量再编辑再 PUT
- [ ] 3.4 编辑「已整合日」时标注「此日已整合，编辑不再入图（仅影响日记重生成）」——据 `GET /consolidate/status` 判该日是否 `done`（D5 取舍的 UX 提示）

## 4. 整合块

- [ ] 4.1 日历总览 `GET /consolidate/statuses` → 每日着色 done / pending / failed
- [ ] 4.2 选日触发 `POST /consolidate` + 状态 `GET /consolidate/status`；回显 done / already / running

## 5. 日记块

- [ ] 5.1 生成 `POST /diary`（无碎片 → 提示 no_fragments）
- [ ] 5.2 查看 `GET /diary/{date}` + 列表 `GET /diaries`

## 6. 召回块（只读 ReAct）

- [ ] 6.1 构只读 agent 实例：`ToolsetConfig(enabled=<去掉 learn 的只读工具集>)`，与主 chat agent 共用同一 `MemoryStore`（复用既有 builder，不改 loop）
- [ ] 6.2 新增 `POST /recall` 端点（挂 mcs_agent app）→ 只读 agent 跑 ReAct → 返回回复
- [ ] 6.3 前端召回框 → 调 `POST /recall` → 渲染回复
- [ ] 6.4 测试：只读召回不写图（召回前后节点 / 边数不变，即便问题措辞像陈述）；只读工具集确实不含 learn

## 7. 图谱块（嵌入，不拥有 graph.html 修复）

> 前置依赖：`graph.html` 与统一模型对齐由独立 change [`graph-renderer-align`](../../graph-renderer-align/proposal.md) 负责，不属本片。本片只嵌入 + 降级。

- [ ] 7.1 在 `manage.html` 内嵌图谱（iframe 复用 graph.html，或抽共用 JS 模块）
- [ ] 7.2 graph.html 未对齐时图谱块"缺块降级"灰显 + 提示，不阻塞其余五块
- [ ] 7.3 待 graph.html 对齐任务落地后，验证嵌入图谱根视图 + 下钻正常

## 8. 验证与文档

- [ ] 8.1 手动走查：六块端到端（记一条 → 整合 → 看图谱节点 → 生成日记 → 召回）
- [ ] 8.2 docs / README：管理看板入口（`/manage.html`）+ 六块说明

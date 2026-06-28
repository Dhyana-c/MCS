## Context

个人记忆系统 4 片拆分的 **Slice 4（管理 UI）**，叠在 Slice 1/2/3 之上，消费它们的 API。目标是一张前端管理页，让用户不碰 curl 就能管理整个记忆系统。

现有可复用：
- `mcs_agent/app.py` 在 `/` 兜底挂 `static/`（`StaticFiles(html=True)`），已有 `index.html`（聊天）、`graph.html`（图谱）、`vendor/cytoscape.min.js`。
- `/chat`（ReAct）、`/graph/expand`（graph_view）已存在。
- 后端 `graph_view` 已输出统一模型字段（`node_class`/`hub`/`type`，无 `relation_model`），见 `graph-visualization` spec。

## Goals / Non-Goals

**Goals:**
1. 一张管理页覆盖：记录 / 碎片编辑 / 整合日历 + 触发 / 日记 / 召回 / 嵌入图谱
2. 纯静态 HTML/JS，零构建，挂现有 `static/`
3. 召回走只读 `/recall`（禁 learn 的只读 agent，见 D2），不在 UI 层另造检索
4. 图谱渲染器对齐统一模型（修现有 `graph.html` 的旧字段债）

**Non-Goals:**
- 除新增只读 `POST /recall`（D2）外，不加新后端端点；六块其余所需端点 Slice 1/2/3 + 现有 `/graph/expand` 已齐
- 不引前端框架 / 构建链（保持"暂时"的轻量）
- 不做多用户 / 鉴权（个人私有）

## Decisions

### D1: 静态页挂 `mcs_agent/static`，无构建

**选择**：新增 `mcs_agent/static/manage.html`（管理看板），与 `index.html`/`graph.html` 同居，经现有 `StaticFiles` 直接可达（`/manage.html`）。纯原生 HTML/CSS/JS + 现有 `vendor/cytoscape.min.js`。

**理由**：用户说"暂时需要"——零构建步骤最省事，与现有两页一致。后续要正式客户端再换框架，不在本片。

### D2: 召回走 ReAct，但只读（禁 learn）

**选择**：管理页"召回"框走 ReAct 召回，渲染回复——但**只读**：召回路径 MUST 禁用 `learn` 工具。

**为何不直接用全功能 `/chat`**：`MemoryAgent` 的 ReAct 工具集含 `learn`（写图）。召回是查询语义，用户问一句不该让 agent 顺手 ingest。直接打全功能 `/chat` 有"召回触发写"的风险。

**选定方案：独立 `POST /recall` 端点 + 只读 agent 实例（复用 `ToolsetConfig`）。**

`mcs_agent` 已有 `ToolsetConfig(enabled=...)` 机制（[builder.py:127](../../../mcs_agent/builder.py)、[loop.py](../../../mcs_agent/loop.py) `build_toolset`），构造时即可按需启用工具子集。故只读召回 = 用 `ToolsetConfig(enabled=<去掉 learn 的只读工具集，如 search/associate/reason/recall>)` 另构一个**只读 `MemoryAgent` 实例**（与主 chat agent 共用同一 `MemoryStore` / MCS），挂 `POST /recall`。

**为何选独立端点而非给 `/chat` 加 `readonly` 参数**：① 复用现成 `ToolsetConfig` + builder，**零侵入** loop（不必让 `chat()` 动态切换工具集）；② 语义清晰——`/recall` 永远只读、`/chat` 永远全功能，不靠运行时 flag 区分；③ 两个 agent 实例共享一个 `MemoryStore`（单 worker / 唯一 MCS），不破坏线程模型。代价：多构造一个 agent 实例（轻量，仅工具集不同）。

**跨层契约（被依赖不变量）**：只读保证由 `mcs_agent.tools.ToolSpec.readonly` 元数据 +
`READONLY_TOOL_NAMES` 白名单承载（已实装——非 `if name != "learn"` 黑名单）。`mcs_agent` 新增
写图工具 MUST 标 `ToolSpec(readonly=False)`，使其自动排除出只读召回；否则静默破坏
"召回 MUST NOT 写图"。

### D3: graph.html 对齐由独立 change 负责，本片只依赖 + 嵌入（不拥有代码债）

**背景**：既有 `graph-visualization` spec（[spec:92](../../specs/graph-visualization/spec.md)）**已要求** `graph.html` 按统一模型渲染（`node_class`/`hub`/`type`、无 label、叶子 = `node_class ∈ {事件, source}`），后端 `graph_view` 也已吐这些字段。但 **`graph.html` 代码仍读旧字段**（`role`/`kind`/`label`/`relation_model`）——代码落后于它自己的 spec。

**选择**：把 graph.html 的对齐**划出本片 scope**，交独立 change [`graph-renderer-align`](../../graph-renderer-align/proposal.md)（它本就是个与个人记忆系统无关的既存 bug，不该由 UI change 承担）。本片对图谱只做两件事：
1. **依赖** graph.html 已按统一模型渲染（前置条件）；
2. 在 `manage.html` **嵌入**图谱（iframe 复用 graph.html，或共用 JS 模块），消费现有 `GET /graph/expand`。

**为何不揽进本片**：graph.html 的旧字段是 `unified-graph-schema` 迁移留下的代码债，独立于"个人记忆管理 UI"这件事。混进来会让本片 scope 模糊、且把一个既存 bug 的修复责任错挂到 UI change 上。本片 scope = `manage.html` + `POST /recall`，仅此。

**若 `graph-renderer-align` 未先落地**：本片的图谱块按"缺块降级"处理（灰显 + 提示），不阻塞看板其余五块（见 D4 风险）。

### D4: 看板布局——六块，单页

```
┌─ manage.html ───────────────────────────────────────┐
│ [记录框] 随手记 → /note                              │
├──────────────┬───────────────────────────────────────┤
│ 碎片列表      │ 碎片编辑器(textarea)                  │
│ /fragments    │ 读 GET /fragments/{date}              │
│ (按日倒排)    │ 存 PUT /fragments/{date}              │
├──────────────┴───────────────────────────────────────┤
│ [整合] 日历(/statuses 着色 done/pending/failed)       │
│        选某天 → 触发 /consolidate · 状态 /status      │
├───────────────────────────────────────────────────────┤
│ [日记] 生成 /diary · 查看 /diary/{date} · 列表 /diaries│
├───────────────────────────────────────────────────────┤
│ [召回框] → /recall (只读 ReAct，禁 learn)             │
├───────────────────────────────────────────────────────┤
│ [图谱] 嵌入 graph_view(/graph/expand)，统一模型渲染   │
└───────────────────────────────────────────────────────┘
```

## Risks / Trade-offs

- **[迁移未完]** `unified-graph-schema` Phase B/C/D/E 未完，`graph_view` 字段未来或再变 → 缓解：以当前实际输出对齐；字段再变时本渲染器同步（同仓库可控）
- **[依赖三片全完]** UI 依赖 Slice 1/2/3 全部端点 → 缓解：UI 可分块上线（先记录 + 碎片编辑，整合 / 日记 / 图谱块按对应片就绪逐块点亮）；本片 tasks 按块拆，缺的块降级灰显
- **[无构建的可维护性]** 原生 JS 单页随功能增多会变长 → 接受："暂时"轻量优先；正式客户端另起
- **[PUT 覆盖丢内容]** 编辑器保存整文件覆盖 → 缓解：编辑器"先 GET 全量再 PUT"，与 Slice 1 D3 契约一致

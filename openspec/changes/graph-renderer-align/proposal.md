## Why

mcs_mem（个人记忆应用）的管理看板需要**自己的图谱可视化**——不依赖 `mcs_agent` 的
`graph.html`（那是 mcs_agent 基础 agent 的简陋前端、且仍读旧字段）。后端 `MemoryStore.graph_view`
已吐**统一模型**字段（`node_class` / `hub` / `type` / `degree`，无 `relation_model`），
本 change 在 `mcs_mem/static/` 自建对齐统一模型的图谱视图，供管理看板嵌入。

> 原始定位（对齐 `mcs_agent/graph.html`）已废弃——经 change `mcs-mem-package-extract` 剥离，
> mcs_mem 不再复用 mcs_agent 前端；`mcs_agent/graph.html` 的旧字段是它自己的债、与本 change 解耦。

## What Changes

- 新建 `mcs_mem/static/graph.html`：Cytoscape 图谱视图，对齐统一模型
  - 节点字段 `node_class`（概念 / 事实 / 事件 / source）+ `hub` + `degree`（热力图）
  - 边字段 `type`（`关联` / `互斥`，无 label）；互斥虚线
  - 下钻判定 `node_class ∈ {概念, 事实}`；叶子 `∈ {事件, source}`
  - 根视图折叠按 `hub === true`
- `mcs_mem/app.py`：`/` → manage.html（主入口）；mount `mcs_mem/static`（提供 /graph.html）；
  不 mount `mcs_agent/static`；vendor（cytoscape 库）复用 `mcs_agent/static/vendor`
- `manage.html`：iframe 嵌入自己的 `/graph.html`（现指向 mcs_mem 自己的）；导航删指向 mcs_agent 的链接

## Capabilities

属 `memory-management-ui`（管理看板的图谱块）——本 change 实装其图谱视图（原 design D3
"嵌入 graph.html"改为"嵌入 mcs_mem 自建图谱视图"）。无独立 spec delta。

## Impact

- 新建 `mcs_mem/static/graph.html`
- 改 `mcs_mem/app.py`（入口 + mount）、`mcs_mem/static/manage.html`（导航）
- 不碰 `mcs_agent/`（graph.html 旧字段是 mcs_agent 自己的债，另议）

## Context

mcs_mem 独立后（change `mcs-mem-package-extract`），管理看板不应复用 `mcs_agent` 的前端。
原 manage.html iframe 嵌入 `mcs_agent/static/graph.html`（简陋、读旧字段 role/kind/label）。
后端 `MemoryStore.graph_view` 已吐统一模型（`node_class` / `hub` / `type` / `degree`）。

本 change 在 `mcs_mem/static/` 自建对齐统一模型的图谱视图。

## Decisions

### D1: 字段对齐统一模型

节点 `node_class` / `hub` / `degree`；边 `type`（关联 / 互斥，无 label）。删 role / kind / label /
relation_model 全部旧字段。

### D2: 下钻 / 叶子按 node_class

可下钻 `node_class ∈ {概念, 事实}`；叶子 `∈ {事件, source}`（不可下钻）。根视图折叠按 `hub === true`。

### D3: manage.html 嵌入自己的 /graph.html

iframe `src="/graph.html"`——经 `mcs_mem/app` mount `mcs_mem/static`，指向 mcs_mem 自己的图谱页
（不再指向 mcs_agent 的）。

### D4: / 入口 + vendor

`/` → manage.html（显式 FileResponse，主入口）。mount `mcs_mem/static` 到 `/`（提供 /graph.html）。
**不** mount `mcs_agent/static`（剥离 mcs_agent 前端）。vendor（cytoscape 库）复用
`mcs_agent/static/vendor`（库非前端、mcs_mem 依赖 mcs_agent、共享可接受）。

## Risks / Trade-offs

- **vendor 复用 mcs_agent**：若要彻底独立，可复制 cytoscape 到 `mcs_mem/static/vendor`（当前共享库可接受）。
- **mcs_agent graph.html 旧字段**：仍是 mcs_agent 自己的前端债（mcs_agent 基础 app 还 mount 它），
  与本 change 解耦、优先级归 mcs_agent。

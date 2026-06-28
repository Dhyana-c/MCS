## 1. mcs_mem/static/graph.html 自建图谱视图

- [x] 1.1 节点 data 用 `node_class` / `hub` / `degree`（删 `role`）
- [x] 1.2 样式 selector：`node[node_class=...]` + `node[hub=true]`；`edge[type=关联]` / `edge[type=互斥]`（虚线）
- [x] 1.3 下钻 `node_class ∈ {概念, 事实}`；叶子 `∈ {事件, source}`；根视图折叠 `hub === true`
- [x] 1.4 删 `relation_model` 显示；节点 / 边详情用 `node_class` / `type`

## 2. mcs_mem/app.py + manage.html

- [x] 2.1 `/` → manage.html（主入口）；mount `mcs_mem/static`（/graph.html）；**不** mount `mcs_agent/static`
- [x] 2.2 vendor（cytoscape）复用 `mcs_agent/static/vendor`
- [x] 2.3 manage.html 导航删指向 mcs_agent 的链接

## 3. 验证

- [ ] 3.1 手动：`/` 与 `/manage.html` → 管理看板；`/graph.html` → mcs_mem 图谱（统一模型）；下钻 / 热力图 / 详情正常
- [ ] 3.2 测试：manage.html 可达、`/graph.html` 可达

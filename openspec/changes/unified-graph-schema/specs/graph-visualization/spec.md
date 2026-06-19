# graph-visualization（delta）

> 只读可视化改写到单一模型：关系边取 `get_relations`（不再按 `relation_model` 分 `get_facts`/`get_assoc`）；序列化去 `relation_model`、节点 `role`→`node_class`、边 `kind`/`label`→`type`；前端按 `type` 渲染、按 `node_class` 判可否下钻。`GET /graph/expand` 端点、纯只读不破不变量等要求不变。

## MODIFIED Requirements

### Requirement: MemoryStore graph_view 只读原语

`MemoryStore` SHALL 提供只读原语 `graph_view(node_id) -> dict | None`，经单 worker 线程（`_submit`）执行：取焦点节点（`get_node`）、其下钻成员（`get_out_hierarchy`）、其关系边（`get_relations`，关联 / 互斥）、关系边的**另一端节点**，序列化为 `{node, nodes, edges}` 返回（`nodes` = 下钻成员 ∪ 关系边端点按 id 去重、不含焦点；`edges` = 下钻边 `焦点→成员` ∪ 关系边）。节点不存在时返回 `None`。**调用方线程 MUST NOT 直接读 `store` / `mcs`**（线程安全铁律）。MUST NOT 再返回 `relation_model` 键。

#### Scenario: 根视图返回焦点、邻居节点、边

- **WHEN** 调用 `graph_view("__seed_root__")`
- **THEN** MUST 返回 dict，其中 `node.id == "__seed_root__"`、`nodes` 为下钻成员与（若有）关系边端点的并集、`edges` 含下钻边与关系边
- **AND** MUST NOT 含 `relation_model` 键

#### Scenario: 关系边取 get_relations

- **WHEN** 调用 `graph_view(id)`
- **THEN** `edges` 中关系边 MUST 来自 `get_relations(id)`（`type ∈ {关联, 互斥}`，无 label）

### Requirement: graph_view 返回结构为 JSON 友好纯 dict

`graph_view` 返回的 `node` 与 `nodes[*]` MUST 为 `{id, name, content, node_class, degree}`（`degree` = 下钻成员数 + 关系边度数，int，供热力图）；`edges[*]` MUST 为 `{id, source, target, type}`（`id` 取 `edge.id`，供前端按 id 去重）。所有字段 MUST 为 JSON 可序列化纯值，MUST NOT 携带 dataclass 实例 / 内部引用。`nodes` MUST 按 id 去重。下钻（组织）边 MUST 为 `{source: 焦点.id, target: 成员.id, type: "关联"}`。MUST NOT 含 `relation_model` / `kind` / `label` / `role` 字段。

#### Scenario: 节点序列化字段

- **WHEN** 序列化任一节点
- **THEN** MUST 含且仅含 `id` / `name` / `content` / `node_class` / `degree`，值为 JSON 可序列化纯值

#### Scenario: 边序列化字段与 type 取值

- **WHEN** 序列化任一边
- **THEN** MUST 含且仅含 `id` / `source` / `target` / `type`
- **AND** `type` MUST ∈ `{"关联", "互斥"}`（下钻边为 `"关联"`）；MUST NOT 含 `kind` / `label`

### Requirement: graph.html 默认渲染根子图并支持点击下钻

`static/graph.html` SHALL 经 Cytoscape.js 在打开时默认拉取 `__seed_root__` 子图（`GET /graph/expand`）渲染；点击**可下钻节点**（`node_class ∈ {概念, 事实}`）时触发 `GET /graph/expand?node_id=<该节点>`，把返回的 `nodes` 与 `edges` **增量并入**（按 id 去重）；返回空的节点标为叶子（首次点击后缓存）；**叶子节点（`node_class ∈ {事件, source}`）不可下钻**（仅作端点显示，点击前可据 `node_class` 预判、不发请求）；关系边按 `type` 渲染（`关联` / `互斥`，**无 label**），下钻（组织）边以区分样式渲染。前端 MUST NOT 自造边，仅渲染后端返回的 `edges`。

#### Scenario: 点击可下钻节点增量并入

- **WHEN** 点击一个 `node_class ∈ {概念, 事实}` 的节点
- **THEN** 前端 MUST 请求 `GET /graph/expand?node_id=<id>` 并把返回 `nodes`/`edges` 按 id 去重并入

#### Scenario: 叶子节点不可下钻

- **WHEN** 节点 `node_class ∈ {事件, source}`
- **THEN** 前端 MUST NOT 对其发下钻请求

#### Scenario: 边按 type 渲染

- **WHEN** 渲染关系边
- **THEN** MUST 按 `type`（`关联` / `互斥`）渲染、无 label；下钻边以区分样式渲染

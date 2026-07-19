# graph-visualization Specification

## Purpose
规定 `MemoryStore.graph_view` 只读原语 + `GET /graph/expand` JSON 端点的契约（本仓履行）；前端 `graph.html` 已随 `mcs-mem` 迁出（本仓不交付），本 spec 保留其前端 Requirement 作为后端契约的前端侧补充。
## Requirements
### Requirement: MemoryStore graph_view 只读原语

`MemoryStore` SHALL 提供只读原语 `graph_view(node_id) -> dict | None`，经单 worker 线程（`_submit`）执行：取焦点节点（`get_node`）、其下钻成员（`get_out_hierarchy`）、其关系边（`get_relations`，关联 / 互斥，载重过滤事件边）、关系边的**另一端节点**、其相关事件（`get_related_events`，绕载重），序列化为 `{node, nodes, edges}` 返回（`nodes` = 下钻成员 ∪ 关系边端点 ∪ 相关事件，按 id 去重、不含焦点；`edges` = 关系边 ∪ 事件→焦点背书边（`get_edges_between` 取），按 `edge.id` 去重）。**可视化为人面视图，用 `get_related_events` 看到事件背书 —— 载重只约束 LLM 查询路径、不约束可视化。** 节点不存在时返回 `None`。**调用方线程 MUST NOT 直接读 `store` / `mcs`**（线程安全铁律）。MUST NOT 再返回 `relation_model` 键。

#### Scenario: 根视图返回焦点、邻居节点、边

- **WHEN** 调用 `graph_view("__seed_root__")`
- **THEN** MUST 返回 dict，其中 `node.id == "__seed_root__"`、`nodes` 为下钻成员、关系边端点与相关事件的并集、`edges` 为关系边与事件→焦点背书边
- **AND** MUST NOT 含 `relation_model` 键

#### Scenario: 节点不存在返回 None

- **WHEN** 调用 `graph_view("<图中不存在的 id>")`
- **THEN** MUST 返回 `None`，MUST NOT 抛异常

#### Scenario: 孤立叶子节点邻居与边均为空

- **WHEN** 调用 `graph_view("<既无下钻成员、又无关系边、又无相关事件的叶子节点 id>")`
- **THEN** 返回的 `nodes` MUST 为空列表 `[]`，`edges` MUST 为空列表 `[]`

#### Scenario: 关系边取 get_relations

- **WHEN** 调用 `graph_view(id)`
- **THEN** `edges` 中关系边 MUST 来自 `get_relations(id)`（`type ∈ {关联, 互斥}`，无 label）

#### Scenario: 事件背书绕载重可见

- **WHEN** 焦点节点被某事件经关联边背书（事件→焦点）
- **THEN** 该事件节点 MUST 出现在 `nodes` 中、事件→焦点边 MUST 出现在 `edges` 中（即便载重让 `get_relations(焦点)` 过滤了事件边）

#### Scenario: 全程经单 worker 线程

- **WHEN** 在 FastAPI 路由线程调用 `graph_view(id)`
- **THEN** 实际的 `get_node` / `get_out_hierarchy` / `get_relations` / `get_related_events` 调用 MUST 在 `MemoryStore` 的单 worker 线程内执行，路由线程 MUST NOT 直接触碰 `store` / `mcs` 实例

---

### Requirement: graph_view 返回结构为 JSON 友好纯 dict

`graph_view` 返回的 `node` 与 `nodes[*]` MUST 为 `{id, name, content, node_class, degree}`（`degree` = 不同邻居数（关系边端点 ∪ 相关事件，去重），int，供热力图）；`edges[*]` MUST 为 `{id, source, target, type}`（`id` 取 `edge.id`，供前端按 id 去重）。所有字段 MUST 为 JSON 可序列化纯值，MUST NOT 携带 dataclass 实例 / 内部引用。`nodes` MUST 按 id 去重。焦点→下钻成员的连线即焦点作 source 的关联边（`get_relations` 已含，统一模型层级=关联），同一对节点 MUST NOT 因另造虚拟边而出现多条。`edges` 按 `edge.id` 去重（关系边 ∪ 事件背书边，兜 store 实现差异）。MUST NOT 含 `relation_model` / `kind` / `label` / `role` 字段。

#### Scenario: 节点序列化字段

- **WHEN** 序列化任一节点
- **THEN** MUST 含且仅含 `id` / `name` / `content` / `node_class` / `degree`，值为 JSON 可序列化纯值

#### Scenario: 边序列化字段与 type 取值

- **WHEN** 序列化任一边
- **THEN** MUST 含且仅含 `id` / `source` / `target` / `type`
- **AND** `type` MUST ∈ `{"关联", "互斥"}`（下钻边为 `"关联"`）；MUST NOT 含 `kind` / `label`

#### Scenario: nodes 按 id 去重

- **WHEN** 某节点既是焦点节点的下钻成员、又是其关系边端点或相关事件
- **THEN** 该节点在 `nodes` 中 MUST 只出现一次

#### Scenario: 下钻连线即关联边、同对节点无重复

- **WHEN** 焦点节点有下钻成员（经关联边挂载，统一模型层级=关联）
- **THEN** `edges` MUST 含焦点→该成员的关联边（`source` 为焦点 `id`、`target` 为成员 `id`、`type == "关联"`，来自 `get_relations`）
- **AND** 同一对 `(source, target, type)` MUST 只出现一条（MUST NOT 另造虚拟 hierarchy 边导致多边）

#### Scenario: degree 反映不同邻居数

- **WHEN** 焦点节点的下钻成员、关系边端点、相关事件存在重叠（统一模型层级=关联，下钻成员即关系端点）
- **THEN** `degree` MUST 等于不同邻居 id 的数量（MUST NOT 对同一邻居因「下钻 + 关系」重复计数）

---

### Requirement: GET /graph/expand 只读 JSON 端点

`create_app` SHALL 提供只读 JSON 端点 `GET /graph/expand?node_id=<id>`（`node_id` 缺省 `__seed_root__`），转发到 `agent.memory.graph_view(node_id)`。节点不存在时返回 `404`；当注入的 agent 无 `memory` 或 `memory` 无 `graph_view` 时（如裸 fake agent）返回 `503` 优雅降级，且 MUST NOT 影响既有 `/chat` 注入测试。

#### Scenario: 缺省参数返回根视图

- **WHEN** `GET /graph/expand`（不带 `node_id`）
- **THEN** MUST 返回 `200`，响应体 `node.id == "__seed_root__"`

#### Scenario: 指定 node_id 返回该节点视图

- **WHEN** `GET /graph/expand?node_id=<存在 id>`
- **THEN** MUST 返回 `200`，响应体 `node.id == <该 id>`

#### Scenario: 不存在 node_id 返回 404

- **WHEN** `GET /graph/expand?node_id=<不存在 id>`
- **THEN** MUST 返回 `404`

#### Scenario: 注入无 memory 的 agent 优雅降级

- **WHEN** `create_app` 注入一个无 `memory` 属性（或 `memory` 无 `graph_view`）的 fake agent
- **THEN** `GET /graph/expand` MUST 返回 `503`
- **AND** 同一 app 的 `/chat` 行为 MUST NOT 被破坏（仍转发到 `fake_agent.chat`）

---

### Requirement: graph.html 默认渲染根子图并支持点击下钻（前端契约，由 mcs-mem repo 履行）

> **本仓不交付 `static/graph.html`**——前端可视化随 `mcs_mem` 迁至独立 repo `mcs-mem`（https://github.com/Dhyana-c/mcs-mem）。
> 以下 SHALL/scenario 由 `mcs-mem` 的前端履行；本 spec 保留之作为 `GET /graph/expand` 后端契约的前端侧补充。本仓履行的后端契约见上三个 Requirement（`graph_view` 只读原语 / JSON 结构 / `/graph/expand` 端点）。

`static/graph.html` SHALL 经 Cytoscape.js 在打开时默认拉取 `__seed_root__` 子图（`GET /graph/expand`）渲染；右键任一节点触发 `GET /graph/expand?node_id=<该节点>`，把返回的 `nodes` 与 `edges` **增量并入**（按 id 去重）；返回空的节点标为叶子（首次点击后缓存）。**事件节点可下钻**（展开其涉及的概念/事实，`事件→核心` 出边）；`source` / 孤立节点 expand 返回空 → 标叶子。关系边按 `type` 渲染（`关联` / `互斥`，**无 label**），下钻（组织）边以区分样式渲染。前端 MUST NOT 自造边，仅渲染后端返回的 `edges`。

#### Scenario: 默认加载根子图

- **WHEN** 打开 `graph.html`
- **THEN** MUST 自动请求 `GET /graph/expand`（缺省根）并渲染 `__seed_root__` 及其 `nodes` / `edges`

#### Scenario: 右键节点增量并入

- **WHEN** 右键一个节点（概念 / 事实 / 事件 均可）
- **THEN** MUST 请求该节点的 `/graph/expand`，并把返回的新 `nodes` / `edges` 并入图（返回空则据下一 scenario 标为叶子）

#### Scenario: 按 id 去重不重复并入

- **WHEN** 对已展开的节点重复点击
- **THEN** MUST NOT 重复并入已存在的节点 / 边

#### Scenario: 叶子节点首次点击后不再重复请求

- **WHEN** 点击一个节点，其 `/graph/expand` 返回 `nodes` 与 `edges` 均空
- **THEN** MUST 将该节点标记为叶子样式
- **AND** 该节点被标记为叶子后，后续点击 MUST NOT 再次发起 `/graph/expand` 请求

#### Scenario: 事件可下钻、source/孤立标叶子

- **WHEN** 右键一个事件节点
- **THEN** MUST 请求其 `/graph/expand` 并并入其涉及的概念/事实（事件→核心出边）
- **AND** `source` / 无邻居的孤立节点 MUST 标为叶子（不再下钻）

#### Scenario: 边按 type 渲染

- **WHEN** 渲染关系边
- **THEN** MUST 按 `type`（`关联` / `互斥`）渲染、无 label；下钻边以区分样式渲染

### Requirement: 可视化纯只读、不破坏核心不变量

`graph_view` 与 `GET /graph/expand` SHALL 纯只读：MUST NOT 调用写管线（`ingest`）/ 守门 / 裂变 / 归纳，MUST NOT 修改图（调用前后节点数、边数、节点内容不变）。可视化为人面视图，MUST NOT 复用或影响 LLM 渲染口径（铁律一仅约束 LLM 上下文 token 口径）。

#### Scenario: graph_view 不改图

- **WHEN** 对任一节点调用 `graph_view` 前后比较整图
- **THEN** 节点数、边数、各节点 content MUST 保持不变

#### Scenario: 端点不触发写入路径

- **WHEN** 反复请求 `GET /graph/expand`
- **THEN** MUST NOT 触发 `ingest` / 守门 / 裂变（写入管线与 `decide_hub` 不被调用）


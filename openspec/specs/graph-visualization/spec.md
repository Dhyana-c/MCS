# graph-visualization Specification

## Purpose
TBD - created by archiving change graph-visualization. Update Purpose after archive.
## Requirements
### Requirement: MemoryStore graph_view 只读原语

`MemoryStore` SHALL 提供只读原语 `graph_view(node_id) -> dict | None`，经单 worker 线程（`_submit`）执行：取焦点节点（`get_node`）、其下钻成员（`get_out_hierarchy`）、其关系边（`get_relations`，关联 / 互斥）、关系边的**另一端节点**，序列化为 `{node, nodes, edges}` 返回（`nodes` = 下钻成员 ∪ 关系边端点按 id 去重、不含焦点；`edges` = 下钻边 `焦点→成员` ∪ 关系边）。节点不存在时返回 `None`。**调用方线程 MUST NOT 直接读 `store` / `mcs`**（线程安全铁律）。MUST NOT 再返回 `relation_model` 键。

#### Scenario: 根视图返回焦点、邻居节点、边

- **WHEN** 调用 `graph_view("__seed_root__")`
- **THEN** MUST 返回 dict，其中 `node.id == "__seed_root__"`、`nodes` 为下钻成员与（若有）关系边端点的并集、`edges` 含下钻边与关系边
- **AND** MUST NOT 含 `relation_model` 键

#### Scenario: 节点不存在返回 None

- **WHEN** 调用 `graph_view("<图中不存在的 id>")`
- **THEN** MUST 返回 `None`，MUST NOT 抛异常

#### Scenario: 孤立叶子节点邻居与边均为空

- **WHEN** 调用 `graph_view("<既无下钻成员、又无关系边的叶子节点 id>")`
- **THEN** 返回的 `nodes` MUST 为空列表 `[]`，`edges` MUST 为空列表 `[]`

#### Scenario: 关系边取 get_relations

- **WHEN** 调用 `graph_view(id)`
- **THEN** `edges` 中关系边 MUST 来自 `get_relations(id)`（`type ∈ {关联, 互斥}`，无 label）

#### Scenario: 全程经单 worker 线程

- **WHEN** 在 FastAPI 路由线程调用 `graph_view(id)`
- **THEN** 实际的 `get_node` / `get_out_hierarchy` / `get_relations` 调用 MUST 在 `MemoryStore` 的单 worker 线程内执行，路由线程 MUST NOT 直接触碰 `store` / `mcs` 实例

---

### Requirement: graph_view 返回结构为 JSON 友好纯 dict

`graph_view` 返回的 `node` 与 `nodes[*]` MUST 为 `{id, name, content, node_class, degree}`（`degree` = 下钻成员数 + 关系边度数，int，供热力图）；`edges[*]` MUST 为 `{id, source, target, type}`（`id` 取 `edge.id`，供前端按 id 去重）。所有字段 MUST 为 JSON 可序列化纯值，MUST NOT 携带 dataclass 实例 / 内部引用。`nodes` MUST 按 id 去重。下钻（组织）边 MUST 为 `{source: 焦点.id, target: 成员.id, type: "关联"}`。MUST NOT 含 `relation_model` / `kind` / `label` / `role` 字段。

#### Scenario: 节点序列化字段

- **WHEN** 序列化任一节点
- **THEN** MUST 含且仅含 `id` / `name` / `content` / `node_class` / `degree`，值为 JSON 可序列化纯值

#### Scenario: 边序列化字段与 type 取值

- **WHEN** 序列化任一边
- **THEN** MUST 含且仅含 `id` / `source` / `target` / `type`
- **AND** `type` MUST ∈ `{"关联", "互斥"}`（下钻边为 `"关联"`）；MUST NOT 含 `kind` / `label`

#### Scenario: nodes 按 id 去重

- **WHEN** 某节点既是焦点节点的下钻成员、又是其关系边端点
- **THEN** 该节点在 `nodes` 中 MUST 只出现一次

#### Scenario: 下钻边由后端给出

- **WHEN** 焦点节点有下钻成员
- **THEN** `edges` MUST 含对应下钻边，其 `source` 为焦点 `id`、`target` 为该成员 `id`、`type == "关联"`

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

### Requirement: graph.html 默认渲染根子图并支持点击下钻

`static/graph.html` SHALL 经 Cytoscape.js 在打开时默认拉取 `__seed_root__` 子图（`GET /graph/expand`）渲染；点击**可下钻节点**（`node_class ∈ {概念, 事实}`）时触发 `GET /graph/expand?node_id=<该节点>`，把返回的 `nodes` 与 `edges` **增量并入**（按 id 去重）；返回空的节点标为叶子（首次点击后缓存）；**叶子节点（`node_class ∈ {事件, source}`）不可下钻**（仅作端点显示，点击前可据 `node_class` 预判、不发请求）；关系边按 `type` 渲染（`关联` / `互斥`，**无 label**），下钻（组织）边以区分样式渲染。前端 MUST NOT 自造边，仅渲染后端返回的 `edges`。

#### Scenario: 默认加载根子图

- **WHEN** 打开 `graph.html`
- **THEN** MUST 自动请求 `GET /graph/expand`（缺省根）并渲染 `__seed_root__` 及其 `nodes` / `edges`

#### Scenario: 点击可下钻节点增量并入

- **WHEN** 点击一个 `node_class ∈ {概念, 事实}` 的节点
- **THEN** MUST 请求该节点的 `/graph/expand`，并把返回的新 `nodes` / `edges` 并入图（返回空则据下一 scenario 标为叶子）

#### Scenario: 按 id 去重不重复并入

- **WHEN** 对已展开的节点重复点击
- **THEN** MUST NOT 重复并入已存在的节点 / 边

#### Scenario: 叶子节点首次点击后不再重复请求

- **WHEN** 点击一个节点，其 `/graph/expand` 返回 `nodes` 与 `edges` 均空
- **THEN** MUST 将该节点标记为叶子样式
- **AND** 该节点被标记为叶子后，后续点击 MUST NOT 再次发起 `/graph/expand` 请求

#### Scenario: 叶子节点不可下钻

- **WHEN** 节点 `node_class ∈ {事件, source}`
- **THEN** MUST NOT 对其发下钻请求（仅作端点显示）

#### Scenario: 边按 type 渲染

- **WHEN** 渲染关系边
- **THEN** MUST 按 `type`（`关联` / `互斥`）渲染、无 label；下钻边以区分样式渲染

---

### Requirement: 可视化纯只读、不破坏核心不变量

`graph_view` 与 `GET /graph/expand` SHALL 纯只读：MUST NOT 调用写管线（`ingest`）/ 守门 / 裂变 / 归纳，MUST NOT 修改图（调用前后节点数、边数、节点内容不变）。可视化为人面视图，MUST NOT 复用或影响 LLM 渲染口径（铁律一仅约束 LLM 上下文 token 口径）。

#### Scenario: graph_view 不改图

- **WHEN** 对任一节点调用 `graph_view` 前后比较整图
- **THEN** 节点数、边数、各节点 content MUST 保持不变

#### Scenario: 端点不触发写入路径

- **WHEN** 反复请求 `GET /graph/expand`
- **THEN** MUST NOT 触发 `ingest` / 守门 / 裂变（写入管线与 `decide_hub` 不被调用）


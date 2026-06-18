# graph-visualization Specification

## Purpose
TBD - created by archiving change graph-visualization. Update Purpose after archive.
## Requirements
### Requirement: MemoryStore graph_view 只读原语

`MemoryStore` SHALL 提供只读原语 `graph_view(node_id) -> dict | None`，经单 worker 线程（`_submit`）执行：取焦点节点（`get_node`）、其层级子节点（`get_out_hierarchy`）、其关系边（按 `mcs.query_engine.relation_model` 分支：`property_graph` 取 `get_facts`、`attribute_node` 取 `get_assoc`）、关系边的**另一端节点**、以及当前 `relation_model`，序列化为 `{node, nodes, edges, relation_model}` 返回（`nodes` = 层级子节点 ∪ 关系边端点节点按 id 去重、不含焦点；`edges` = hierarchy 边 `焦点→子` ∪ 关系边）。节点不存在时返回 `None`。**调用方线程 MUST NOT 直接读 `store` / `mcs`**（线程安全铁律：MCS 非线程安全 + SQLite 线程亲和）。

#### Scenario: 根视图返回焦点、邻居节点、边与 relation_model

- **WHEN** 调用 `graph_view("__seed_root__")`
- **THEN** MUST 返回 dict，其中 `node.id == "__seed_root__"`、`nodes` 为 `get_out_hierarchy("__seed_root__")` 与（若有）关系边端点的并集、`edges` 含 hierarchy 边、且含 `relation_model` 键

#### Scenario: 节点不存在返回 None

- **WHEN** 调用 `graph_view("<图中不存在的 id>")`
- **THEN** MUST 返回 `None`，MUST NOT 抛异常

#### Scenario: 孤立叶子节点邻居与边均为空

- **WHEN** 调用 `graph_view("<既无层级子节点、又无关系边的叶子节点 id>")`
- **THEN** 返回的 `nodes` MUST 为空列表 `[]`，`edges` MUST 为空列表 `[]`

#### Scenario: property_graph 模式取事实边并返回端点节点

- **WHEN** `relation_model == "property_graph"` 时调用 `graph_view(id)`
- **THEN** `edges` 中 `kind=="fact"` 的边 MUST 来自 `get_facts(id)`、`label` 原样保留（非空）
- **AND** 每条 fact 边的另一端节点 MUST 出现在 `nodes` 中

#### Scenario: attribute_node 模式取关联边并返回属性节点

- **WHEN** `relation_model == "attribute_node"` 时调用 `graph_view(id)`
- **THEN** `edges` 中 `kind=="assoc"` 的边 MUST 来自 `get_assoc(id)`、`label` 为空串
- **AND** 每条 assoc 边的端点节点（`role=="attribute"` 的属性节点）MUST 出现在 `nodes` 中

#### Scenario: 全程经单 worker 线程

- **WHEN** 在 FastAPI 路由线程调用 `graph_view(id)`
- **THEN** 实际的 `get_node` / `get_out_hierarchy` / `get_facts` / `get_assoc` 调用 MUST 在 `MemoryStore` 的单 worker 线程内执行，路由线程 MUST NOT 直接触碰 `store` / `mcs` 实例

---

### Requirement: graph_view 返回结构为 JSON 友好纯 dict

`graph_view` 返回的 `node` 与 `nodes[*]` MUST 为 `{id, name, content, role}`；`edges[*]` MUST 为 `{id, source, target, kind, label}`（`id` 取 `edge.id`，供前端按 id 去重）；顶层 MUST 含 `relation_model`。所有字段 MUST 为 JSON 可序列化的纯值，MUST NOT 携带 dataclass 实例或内部对象引用。`nodes` MUST 按 id 去重（既为层级子节点又为关系端点的节点只出现一次）。`edges` 中 hierarchy 边 MUST 为 `{source: 焦点.id, target: 层级子.id, kind: "hierarchy", label: ""}`。

#### Scenario: 节点序列化字段

- **WHEN** `graph_view` 返回任一节点（`node` 或 `nodes[*]`）
- **THEN** MUST 含且仅含 `id` / `name` / `content` / `role` 四个键，且值为 JSON 可序列化纯值

#### Scenario: 边序列化字段与 kind 取值

- **WHEN** `graph_view` 返回任一 `edges[*]`
- **THEN** MUST 含且仅含 `id` / `source` / `target` / `kind` / `label` 五个键
- **AND** `kind` MUST ∈ `{"hierarchy", "fact", "assoc"}`

#### Scenario: 顶层携带 relation_model

- **WHEN** `graph_view` 返回
- **THEN** 顶层 MUST 含 `relation_model` 键，值为 `"property_graph"` 或 `"attribute_node"`

#### Scenario: nodes 按 id 去重

- **WHEN** 某节点既是焦点节点的层级子节点、又是其关系边端点
- **THEN** 该节点在 `nodes` 中 MUST 只出现一次

#### Scenario: hierarchy 边由后端给出

- **WHEN** 焦点节点有层级子节点
- **THEN** `edges` MUST 含对应 hierarchy 边，其 `source` 为焦点 `id`、`target` 为该层级子节点 `id`、`kind == "hierarchy"`、`label == ""`

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

`static/graph.html` SHALL 经 Cytoscape.js 在打开时默认拉取 `__seed_root__` 子图（`GET /graph/expand`）渲染；点击 `role != "attribute"` 的节点时触发 `GET /graph/expand?node_id=<该节点>`，把返回的 `nodes` 与 `edges` **增量并入**图（按 id 去重）；返回 `nodes` 与 `edges` 均空的节点标为叶子（**首次点击后**判定并缓存，后续不再展开）；`role=="attribute"` 的属性节点不可下钻（仅作关系端点显示，点击前可据 `role` 预判、不发请求）；关系边按 `relation_model` 渲染（`property_graph` 事实边带 label、`attribute_node` 关联边无 label），hierarchy 边以区分样式渲染。前端 MUST NOT 自造边，仅渲染后端返回的 `edges`。

#### Scenario: 默认加载根子图

- **WHEN** 打开 `graph.html`
- **THEN** MUST 自动请求 `GET /graph/expand`（缺省根）并渲染 `__seed_root__` 及其 `nodes` / `edges`

#### Scenario: 点击非 attribute 节点触发下钻并入

- **WHEN** 点击一个 `role != "attribute"` 的节点
- **THEN** MUST 请求该节点的 `/graph/expand`，并把返回的新 `nodes` / `edges` 并入图（返回空则据下一 scenario 标为叶子）

#### Scenario: 按 id 去重不重复并入

- **WHEN** 对已展开的节点重复点击
- **THEN** MUST NOT 重复并入已存在的节点 / 边

#### Scenario: 叶子节点首次点击后不再重复请求

- **WHEN** 点击一个节点，其 `/graph/expand` 返回 `nodes` 与 `edges` 均空
- **THEN** MUST 将该节点标记为叶子样式
- **AND** 该节点被标记为叶子后，后续点击 MUST NOT 再次发起 `/graph/expand` 请求

#### Scenario: attribute 节点不可下钻

- **WHEN** 点击 `role == "attribute"` 的属性节点
- **THEN** MUST NOT 发起下钻请求（仅作关系端点显示）

#### Scenario: 边按 kind 与 relation_model 渲染

- **WHEN** `relation_model == "property_graph"`
- **THEN** `kind=="fact"` 边 MUST 渲染为带 label 的连线、`kind=="hierarchy"` 边以区分样式（如实线）渲染
- **AND** 当 `relation_model == "attribute_node"` 时 `kind=="assoc"` 边 MUST 渲染为无 label 的连线

---

### Requirement: 可视化纯只读、不破坏核心不变量

`graph_view` 与 `GET /graph/expand` SHALL 纯只读：MUST NOT 调用写管线（`ingest`）/ 守门 / 裂变 / 归纳，MUST NOT 修改图（调用前后节点数、边数、节点内容不变）。可视化为人面视图，MUST NOT 复用或影响 LLM 渲染口径（铁律一仅约束 LLM 上下文 token 口径）。

#### Scenario: graph_view 不改图

- **WHEN** 对任一节点调用 `graph_view` 前后比较整图
- **THEN** 节点数、边数、各节点 content MUST 保持不变

#### Scenario: 端点不触发写入路径

- **WHEN** 反复请求 `GET /graph/expand`
- **THEN** MUST NOT 触发 `ingest` / 守门 / 裂变（写入管线与 `decide_hub` 不被调用）


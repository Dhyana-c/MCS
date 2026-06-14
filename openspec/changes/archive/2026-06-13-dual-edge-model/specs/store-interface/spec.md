## MODIFIED Requirements

### Requirement: StoreInterface 定义统一存储抽象基类

`StoreInterface` SHALL 提供区分 `kind`、支持事实边两端可达与 priority 排序的边 API：

**边 CRUD：**
- `add_edge(source_id, target_id, kind="hierarchy", label="", priority=0.0) -> str` — `kind` MUST 为 `"hierarchy"` 或 `"fact"`；事实边 `label` MUST 非空，层级边 `label` MUST 为空串
- `delete_edge(edge_id)` / `update_edge(edge_id, **fields)` — 以**边 `id`** 为键（`add_edge` 返回的 `id`）
- `get_edges_between(source_id, target_id) -> list[Edge]` — 两节点间**全部**边；**取代旧 `get_edge(source, target)`**——同对节点可有多条 fact 边后单返回语义歧义，故 `get_edge(source, target)` 移除

**层级（骨架）查询：**
- `get_out_hierarchy(node_id) -> list[Node]` — 该节点的层级出边目标（驱动导航下钻）

**事实（双向可达）查询：**
- `get_facts(node_id, limit=None) -> list[Edge]` — 返回该节点作**源或宾**的事实边（反查，供查询视图）。**Phase 2** 按 `priority` 降序、`limit` 截断 top-K；**Phase 1** `priority` 未用，返回全部（`limit` 仅作可选上限）
- `get_out_facts(node_id, limit=None) -> list[Edge]` — 仅返回该节点**为源**的事实出边（供 **Phase 2 查询视图估算 / 写入**；fanout 触发口径**不含事实**，见 `subgraph-bounding`「fanout 口径不含事实」）

事实边 MUST **只存一份**（`主→宾`），但两端邻接索引 MUST 都能取到它。系统 MUST NOT 为同一事实双向对存；MUST NOT 提供 `bidirectional` 边或 `direction` 参数。消费者（QueryEngine、WritePipeline、插件）MUST 依赖 `StoreInterface` 而非具体实现。

#### Scenario: 消费者依赖统一接口

- **WHEN** `QueryEngine` 或 `WritePipeline` 初始化接收 store 参数
- **THEN** 参数类型 MUST 为 `StoreInterface`

#### Scenario: get_out_hierarchy 只返回层级出边

- **WHEN** 节点 A 有层级出边到 H、事实边到 C
- **THEN** `get_out_hierarchy(A)` MUST 只返回 H，MUST NOT 返回 C

#### Scenario: get_facts 反查命中

- **WHEN** 存在事实边 `小明 —喜欢→ 苹果`
- **THEN** `get_facts(小明)` 与 `get_facts(苹果)` MUST 都包含这条事实

#### Scenario: get_out_facts 只含出向事实

- **WHEN** 存在事实边 `小明 —喜欢→ 苹果`
- **THEN** `get_out_facts(小明)` MUST 含该边、`get_out_facts(苹果)` MUST NOT 含（苹果是宾，仅入向）

#### Scenario: get_facts 反查并保留 priority 口子

- **WHEN** 调用 `get_facts(node_id, limit=K)`
- **THEN** Phase 2 MUST 按 `priority` 降序返回前 K 条；Phase 1 返回该节点全部事实（`limit` 仅作可选上限，不依赖 priority）

#### Scenario: 事实边只存一份

- **WHEN** 写入事实 `小明 —喜欢→ 苹果`
- **THEN** 存储 MUST 只含一条 `kind="fact"` 边，MUST NOT 含其反向副本

#### Scenario: get_edges_between 返回同对全部边

- **WHEN** 节点 A、B 间有 1 条 hierarchy 边与 2 条不同 label 的 fact 边
- **THEN** `get_edges_between(A, B)` MUST 返回 3 条；`get_edge(A, B)` MUST 不再提供

---

## REMOVED Requirements

### Requirement: 边持久化为有向二元组

**Reason**：边模型从纯二元组 `(source_id, target_id)` 扩展为含 `kind` / `label` / `priority`；由下方新增「边持久化含 kind / label / priority」取代。

### Requirement: StoreInterface 提供 add_bidirectional 辅助方法

**Reason**：事实边改为**一条存一份、两端可达（反查）**，不再以两条对向单向边表达双向关系；`add_bidirectional`（一次写 `a→b` + `b→a`）与该模型冲突，移除。

---

## ADDED Requirements

### Requirement: 边持久化含 kind / label / priority

边表 schema MUST 含 `id, source_id, target_id, kind, label, priority`，PRIMARY KEY 为 `id`，并在 `source_id`、`target_id` 上建索引以支持两端可达查询。`save_full` / `load` round-trip MUST 逐条保真（含 kind / label / priority）。

#### Scenario: 边表含新列

- **WHEN** 建表或落库边
- **THEN** 边记录 MUST 含 `(id, source_id, target_id, kind, label, priority)`

#### Scenario: round-trip 保真

- **WHEN** 含层级边与事实边的图 `save_full` 后 `load`
- **THEN** 加载的边集合 MUST 与落库前逐条一致（含 kind / label / priority）

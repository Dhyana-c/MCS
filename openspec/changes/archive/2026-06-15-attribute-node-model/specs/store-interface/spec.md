## MODIFIED Requirements

### Requirement: StoreInterface 定义统一存储抽象基类

`StoreInterface` SHALL 提供区分 `kind`、支持事实边 / 关联边两端可达与 priority 排序的边 API：

**边 CRUD：**
- `add_edge(source_id, target_id, kind="hierarchy", label="", priority=0.0) -> str` — `kind` MUST 为 `"hierarchy"`、`"fact"` 或 `"assoc"`；事实边（`fact`）`label` MUST 非空，层级边（`hierarchy`）与关联边（`assoc`）`label` MUST 为空串
- `delete_edge(edge_id)` / `update_edge(edge_id, **fields)` — 以**边 `id`** 为键（`add_edge` 返回的 `id`）
- `get_edges_between(source_id, target_id) -> list[Edge]` — 两节点间**全部**边；**取代旧 `get_edge(source, target)`**——同对节点可有多条 fact 边后单返回语义歧义，故 `get_edge(source, target)` 移除

**层级（骨架）查询：**
- `get_out_hierarchy(node_id) -> list[Node]` — 该节点的层级出边目标（驱动导航下钻）

**事实（双向可达）查询：**
- `get_facts(node_id, limit=None) -> list[Edge]` — 返回该节点作**源或宾**的事实边（反查，供查询视图）。**Phase 2** 按 `priority` 降序、`limit` 截断 top-K；**Phase 1** `priority` 未用，返回全部（`limit` 仅作可选上限）
- `get_out_facts(node_id, limit=None) -> list[Edge]` — 仅返回该节点**为源**的事实出边（供 **Phase 2 查询视图估算 / 写入**；fanout 触发口径**不含事实**，见 `subgraph-bounding`「fanout 口径不含事实」）

**关联（无类型、双向可达）查询（`attribute_node` 模式）：**
- `get_assoc(node_id, limit=None) -> list[Edge]` — 返回该节点作**任一端**的 `kind="assoc"` 无类型关联边（反查，供 `attribute_node` 模式查询视图）。`property_graph` 模式通常无 assoc 边、返回空

事实边 / 关联边 MUST **只存一份**（`主→宾`），但两端邻接索引 MUST 都能取到它。系统 MUST NOT 为同一边双向对存；MUST NOT 提供 `bidirectional` 边或 `direction` 参数。消费者（QueryEngine、WritePipeline、插件）MUST 依赖 `StoreInterface` 而非具体实现。

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

#### Scenario: add_edge 接受 assoc kind

- **WHEN** 调用 `add_edge(A, B, kind="assoc")`
- **THEN** 系统 MUST 创建一条 `kind="assoc"`、`label` 为空串的边，两端邻接索引都可取到

#### Scenario: get_assoc 反查命中

- **WHEN** 存在关联边 `小明 —assoc— 小明的爱好`
- **THEN** `get_assoc(小明)` 与 `get_assoc(小明的爱好)` MUST 都包含这条边

# store-interface（delta）

> 存储边 API 随单一模型改写：`add_edge` 用 `type`（仅 `关联` / `互斥`）取代 `kind` + `label`；`get_facts` / `get_out_facts` / `get_assoc` 合并为单一 `get_relations`（关联 / 互斥，两端可达）；持久化列 `kind` / `label` → `type`。`get_out_hierarchy`（下钻）保留——其"组织成员"由聚类涌现的关联 + hub 标记表达（精确判据见 `docs/graph-model-design.md` 开放问题）。其余（InMemory/SQLite 实现、反向邻接表、图级 meta kv）不变。

## MODIFIED Requirements

### Requirement: StoreInterface 定义统一存储抽象基类

`StoreInterface` SHALL 提供基于 `type`、支持关系边两端可达与 priority 排序的边 API：

**边 CRUD：**
- `add_edge(source_id, target_id, type="关联", priority=0.0) -> str` — `type` MUST ∈ 已登记类型（当前 `关联` / `互斥`）；MUST NOT 接受 `kind` / `label` 参数
- `delete_edge(edge_id)` / `update_edge(edge_id, **fields)` — 以**边 `id`** 为键
- `get_edges_between(source_id, target_id) -> list[Edge]` — 两节点间全部边

**下钻（组织骨架）查询：**
- `get_out_hierarchy(node_id) -> list[Node]` — 该节点作组织中心时的下钻成员（由聚类涌现的关联 + hub 标记表达，驱动导航下钻）

**关系（两端可达）查询：**
- `get_relations(node_id, limit=None) -> list[Edge]` — 返回该节点作**任一端**的 `关联` / `互斥` 边（反查，供查询视图）。**取代 `get_facts` / `get_out_facts` / `get_assoc`**。**载重规则（核心不反查事件）**：当 `node` 为**核心节点**（`node_class ∈ {概念, 事实}`）时，MUST 过滤掉**对端为事件**（`node_class=事件`）的关联边——核心节点取不到事件边；事件节点（`node_class=事件`）侧 `get_relations` 仍可达其连向核心的边。**Phase 2** 在过滤后的边集上按 `priority` 降序、`limit` 截断 top-K；**Phase 1** 返回全部（`limit` 仅作可选上限，载重过滤仍生效）。

关系边 MUST **只存一份**（`主→宾`），两端邻接索引 MUST 都能取到；MUST NOT 双向对存、MUST NOT 提供 `bidirectional` / `direction` 参数。消费者 MUST 依赖 `StoreInterface` 而非具体实现。

#### Scenario: 消费者依赖统一接口

- **WHEN** `QueryEngine` 或 `WritePipeline` 初始化接收 store 参数
- **THEN** 参数类型 MUST 为 `StoreInterface`

#### Scenario: add_edge 用 type、拒绝 kind/label

- **WHEN** 调用 `add_edge(A, B, type="互斥")`
- **THEN** 系统 MUST 创建一条 `type="互斥"` 边，两端邻接索引都可取到
- **AND** `add_edge` MUST NOT 接受 `kind` / `label` 参数

#### Scenario: get_relations 反查命中

- **WHEN** 存在关联边连 `小明` 与命题"小明喜欢苹果"
- **THEN** `get_relations(小明)` 与 `get_relations(该命题)` MUST 都包含这条边

#### Scenario: 关系边只存一份

- **WHEN** 写入一条关联 / 互斥边
- **THEN** 存储 MUST 只含一条边，MUST NOT 含其反向副本

#### Scenario: 核心节点不反查事件边

- **WHEN** 存在 `事件 —关联— 概念` 边（如"用户"概念连着某事件）
- **THEN** `get_relations("用户")` MUST NOT 返回该事件边（核心不反查事件）
- **AND** `get_relations(该事件)` MUST 返回该边（事件侧可达核心）
- **AND** 核心节点的 `priority` 截断 MUST 在排除事件边后的样本上进行

#### Scenario: get_edges_between 返回同对全部边

- **WHEN** 节点 A、B 间有多条边
- **THEN** `get_edges_between(A, B)` MUST 返回全部

### Requirement: 边持久化含 type / priority

边表 schema MUST 含 `id, source_id, target_id, type, priority`（`type` 取代 `kind` + `label`），PRIMARY KEY 为 `id`，并在 `source_id`、`target_id` 上建索引以支持两端可达查询。`save_full` / `load` round-trip MUST 逐条保真（含 `type` / `priority` / `extensions`）。

#### Scenario: 边表含 type 列

- **WHEN** 建表或落库边
- **THEN** 边记录 MUST 含 `(id, source_id, target_id, type, priority)`，MUST NOT 含 `kind` / `label` 列

#### Scenario: round-trip 保真

- **WHEN** 含关联边与互斥边的图 `save_full` 后 `load`
- **THEN** 加载的边集合 MUST 与落库前逐条一致（含 `type` / `priority`）

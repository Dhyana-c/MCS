# store-interface Specification

## Purpose
定义统一存储抽象基类，合并图操作（CRUD + 查询）与持久化钩子（save/load/commit/save_full）为单一接口，使消费者（QueryEngine、WritePipeline、插件）依赖接口而非具体实现，支持未来扩展不同存储后端。

## Requirements

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

#### Scenario: get_out_hierarchy 只返回下钻成员

- **WHEN** 节点 A 有下钻成员 H、关联边到 C
- **THEN** `get_out_hierarchy(A)` MUST 只返回 H，MUST NOT 返回 C

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

---

### Requirement: InMemoryStore 实现 StoreInterface

系统 SHALL 提供 `InMemoryStore` 作为 `StoreInterface` 的默认实现，位于 `mcs/stores/in_memory.py`，使用 `dict` 存储节点/边/邻接关系。

#### Scenario: 持久化钩子为空操作

- **WHEN** 调用 `InMemoryStore.save()` 或 `InMemoryStore.load()`
- **THEN** MUST 为空操作（不报错，不持久化）

---

### Requirement: SQLiteStore 实现 StoreInterface

系统 SHALL 提供 `SQLiteStore` 作为 `StoreInterface` 的 SQLite 实现，位于 `mcs/stores/sqlite_store.py`，直接在 SQLite 上做图操作。

#### Scenario: 持久化钩子写入 SQLite

- **WHEN** 调用 `SQLiteStore.save()`
- **THEN** MUST 把当前图状态写入 SQLite 数据库

#### Scenario: load 从 SQLite 加载

- **WHEN** 调用 `SQLiteStore.load()`
- **THEN** MUST 从 SQLite 数据库加载节点和边到内存

---

### Requirement: 边持久化含 type / priority

边表 schema MUST 含 `id, source_id, target_id, type, priority`（`type` 取代 `kind` + `label`），PRIMARY KEY 为 `id`，并在 `source_id`、`target_id` 上建索引以支持两端可达查询。`save_full` / `load` round-trip MUST 逐条保真（含 `type` / `priority` / `extensions`）。

#### Scenario: 边表含 type 列

- **WHEN** 建表或落库边
- **THEN** 边记录 MUST 含 `(id, source_id, target_id, type, priority)`，MUST NOT 含 `kind` / `label` 列

#### Scenario: round-trip 保真

- **WHEN** 含关联边与互斥边的图 `save_full` 后 `load`
- **THEN** 加载的边集合 MUST 与落库前逐条一致（含 `type` / `priority`）

---

### Requirement: SQLiteStore 维护反向邻接表

`SQLiteStore` SHALL 维护反向邻接表 `_reverse_adjacency`（`target_id → {source_id}`），与正向邻接表 `_adjacency`（`source_id → {target_id}`）保持同步。任何改变图拓扑的操作（`add_edge` / `delete_edge` / `delete_node`）SHALL 同时更新正向与反向两张邻接表；`delete_node` 查找入边时 MUST 仅遍历 `_reverse_adjacency` 而非全表扫描；`load()` 从持久层重建图后 SHALL 重建 `_reverse_adjacency` 使其与 `_adjacency` 一致。

#### Scenario: add_edge 同步更新反向索引

- **WHEN** `add_edge(A, B)` 被调用
- **THEN** MUST 同时更新 `_adjacency[A].add(B)` 和 `_reverse_adjacency[B].add(A)`

#### Scenario: delete_edge 同步更新反向索引

- **WHEN** `delete_edge(A, B)` 被调用
- **THEN** MUST 同时更新 `_adjacency[A].discard(B)` 和 `_reverse_adjacency[B].discard(A)`

#### Scenario: delete_node 使用反向索引查找入边

- **WHEN** `delete_node(X)` 查找指向 X 的入边
- **THEN** MUST 仅遍历 `_reverse_adjacency.get(X, set())` 中的节点；MUST NOT 遍历 `self._adjacency` 的全部键

#### Scenario: load 时重建反向索引

- **WHEN** `SQLiteStore.load()` 从持久层加载图数据
- **THEN** MUST 在加载完成后重建 `_reverse_adjacency`，使其与 `_adjacency` 保持一致

---

### Requirement: StoreInterface 图级元数据 kv 原语

`StoreInterface` SHALL 提供图级元数据 key-value 原语（图级、非节点字段）：

- `get_graph_meta(key: str) -> str | None` — 取图级 meta；key 不存在返回 None
- `set_graph_meta(key: str, value: str) -> None` — 写 / 覆盖图级 meta

图级 meta MUST NOT 作为节点 content / summary / extension；MUST NOT 进入节点活跃视图 token 口径。消费者（如 `GraphSummaryPlugin`、`MemoryStore`）经此原语读写图级元数据（如图摘要）。

#### Scenario: get 不存在 key 返回 None

- **WHEN** 调用 `get_graph_meta("absent")`
- **THEN** MUST 返回 None

#### Scenario: set 后 get 命中

- **WHEN** `set_graph_meta("graph_summary", "X")` 后 `get_graph_meta("graph_summary")`
- **THEN** MUST 返回 "X"

#### Scenario: set 覆盖

- **WHEN** 对同 key 两次 `set_graph_meta`
- **THEN** 后值 MUST 覆盖前值

---

### Requirement: 图级 meta 持久化（复用 meta 表）

`SQLiteStore` SHALL 复用既有通用 `meta(key TEXT PRIMARY KEY, value TEXT)` 表持久化图级 meta（与 provenance 同表、按 key 区分；图摘要 key = "graph_summary"），MUST NOT 新建独立表（最小改动，复用既有 kv 基础设施）。`set_graph_meta` 即时落库；跨实例 `initialize` + `load` 后 `get_graph_meta` MUST 保真。`InMemoryStore` 以 dict 承载、持久化钩子维持既有空操作语义。

#### Scenario: SQLite 跨实例 round-trip 保真

- **WHEN** 设若干图级 meta 后，新实例 `initialize` + `load`
- **THEN** 新实例 `get_graph_meta` MUST 与写入逐条一致

#### Scenario: 与 provenance 同表共存

- **WHEN** 写入图摘要且库含 provenance（`schema_version` 等）
- **THEN** 两者 MUST 同表共存、按 key 区分、互不覆盖

#### Scenario: InMemoryStore 承载 meta

- **WHEN** `InMemoryStore.set_graph_meta` 后 `get_graph_meta`
- **THEN** MUST 命中（dict 承载）


# store-interface Specification

## Purpose
定义统一存储抽象基类，合并图操作（CRUD + 查询）与持久化钩子（save/load/commit/save_full）为单一接口，使消费者（QueryEngine、WritePipeline、插件）依赖接口而非具体实现，支持未来扩展不同存储后端。

## Requirements

### Requirement: StoreInterface 定义统一存储抽象基类

系统 SHALL 定义 `StoreInterface` 为 `abc.ABC`，合并 `GraphStoreInterface` 和 `StorageInterface` 的全部方法：

**节点 CRUD：**
- `add_node(node: Node) -> str`
- `get_node(node_id: str) -> Node | None`
- `update_node(node_id: str, updates: dict) -> None`
- `delete_node(node_id: str) -> None`

**边 CRUD（单向）：**
- `add_edge(source_id: str, target_id: str) -> None` — 加入有向边 `source→target`；MUST NOT 含 `direction` 参数
- `get_edge(source_id: str, target_id: str) -> Edge | None`
- `delete_edge(source_id: str, target_id: str) -> None`

**查询：**
- `get_neighbors(node_id: str) -> list[Node]` — 返回该节点的**出邻居**（其为源的有向边目标）
- `get_out_neighbors(node_id: str) -> list[Node]` — 与 `get_neighbors` 同义（保留以减小迁移面）
- `get_subgraph(node_id: str, token_budget: TokenBudget | None = None) -> Subgraph`
- `get_all_nodes() -> list[Node]`
- `get_all_edges() -> list[Edge]`

**持久化钩子：**
- `save() -> None` — 持久化当前状态
- `load() -> None` — 从持久层加载（初始化时调用）
- `commit() -> None` — 提交挂起写入
- `save_full() -> None` — 全量重建持久化

所有边一律为单向 `source→target`；系统 MUST NOT 提供 `bidirectional` 边类型或 `direction` 参数。

#### Scenario: 消费者依赖统一接口

- **WHEN** `QueryEngine` 或 `WritePipeline` 初始化接收 store 参数
- **THEN** 参数类型 MUST 为 `StoreInterface`

#### Scenario: 实现类必须继承 ABC

- **WHEN** 创建新的存储后端（如 SQLiteStore、PostgresStore）
- **THEN** MUST 继承 `StoreInterface` 并实现全部抽象方法

#### Scenario: add_edge 无方向参数且仅维护出邻接

- **WHEN** 调用 `add_edge(a, b)`
- **THEN** 仅 `a` 的邻接含 `b`；`get_neighbors(a)` MUST 含 `b`，`get_neighbors(b)` MUST NOT 因此含 `a`；签名 MUST NOT 含 `direction`

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

### Requirement: 边持久化为有向二元组

SQLite 边表 schema MUST 为有向二元组 `(source_id, target_id)`，MUST NOT 含 `direction` 列。`save_full` / `load` round-trip MUST 逐条保真。

#### Scenario: 边表无 direction 列

- **WHEN** 建表或落库边
- **THEN** 边记录 MUST 仅含 `(source_id, target_id)`；MUST NOT 含 `direction` 列

#### Scenario: round-trip 保真

- **WHEN** 含单向边的图 `save_full` 后 `load`
- **THEN** 加载的边集合 MUST 与落库前逐条 `(source_id, target_id)` 一致

---

### Requirement: SQLiteStore 维护反向邻接表

`SQLiteStore` SHALL 维护 `_reverse_adjacency: dict[str, set[str]]`，在 `add_edge` 和 `delete_edge` 时同步更新。`delete_node` 查找入边时 MUST 使用 `_reverse_adjacency` 而非遍历全图。

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

### Requirement: StoreInterface 提供 add_bidirectional 辅助方法

`StoreInterface` SHALL 提供 `add_bidirectional(source_id: str, target_id: str) -> None` 方法，一次性添加两条单向边 `source→target` 和 `target→source`。

#### Scenario: 语义边一次性添加

- **WHEN** `add_bidirectional(A, B)` 被调用
- **THEN** MUST 等价于调用 `add_edge(A, B)` + `add_edge(B, A)`

#### Scenario: 接口定义为非抽象

- **WHEN** 检查 `StoreInterface.add_bidirectional`
- **THEN** MUST 为带默认实现的方法（默认调用两次 `add_edge`）；子类 MAY 覆写以优化（如减少存在性检查）

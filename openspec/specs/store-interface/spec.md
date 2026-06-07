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

**边 CRUD：**
- `add_edge(source_id: str, target_id: str, direction: str = "bidirectional") -> None`
- `get_edge(source_id: str, target_id: str) -> Edge | None`
- `delete_edge(source_id: str, target_id: str) -> None`

**查询：**
- `get_neighbors(node_id: str) -> list[Node]`
- `get_out_neighbors(node_id: str) -> list[Node]`
- `get_subgraph(node_id: str, token_budget: TokenBudget | None = None) -> Subgraph`
- `get_all_nodes() -> list[Node]`
- `get_all_edges() -> list[Edge]`

**持久化钩子：**
- `save() -> None` — 持久化当前状态
- `load() -> None` — 从持久层加载（初始化时调用）
- `commit() -> None` — 提交挂起写入
- `save_full() -> None` — 全量重建持久化

#### Scenario: 消费者依赖统一接口

- **WHEN** `QueryEngine` 或 `WritePipeline` 初始化接收 store 参数
- **THEN** 参数类型 MUST 为 `StoreInterface`

#### Scenario: 实现类必须继承 ABC

- **WHEN** 创建新的存储后端（如 SQLiteStore、PostgresStore）
- **THEN** MUST 继承 `StoreInterface` 并实现全部抽象方法

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

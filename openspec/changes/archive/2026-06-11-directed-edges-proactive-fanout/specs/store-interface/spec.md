## MODIFIED Requirements

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

## ADDED Requirements

### Requirement: 边持久化为有向二元组

SQLite 边表 schema MUST 为有向二元组 `(source_id, target_id)`，MUST NOT 含 `direction` 列。`save_full` / `load` round-trip MUST 逐条保真。

#### Scenario: 边表无 direction 列

- **WHEN** 建表或落库边
- **THEN** 边记录 MUST 仅含 `(source_id, target_id)`；MUST NOT 含 `direction` 列

#### Scenario: round-trip 保真

- **WHEN** 含单向边的图 `save_full` 后 `load`
- **THEN** 加载的边集合 MUST 与落库前逐条 `(source_id, target_id)` 一致

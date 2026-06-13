## MODIFIED Requirements

### Requirement: StoreInterface 定义统一存储抽象基类

系统 SHALL 定义 `StoreInterface` 为 `abc.ABC`，合并 `GraphStoreInterface` 和 `StorageInterface` 的全部方法：

**节点 CRUD：**
- `add_node(node: Node) -> str`
- `get_node(node_id: str) -> Node | None`
- `update_node(node_id: str, updates: dict) -> None`
- `delete_node(node_id: str) -> None`

**边 CRUD（支持类型和标签）：**
- `add_edge(source_id: str, target_id: str, edge_type: str = "neighbor", label: str = "") -> str` — 加入有向边，返回边 ID；`edge_type` MUST 为 `"neighbor"` 或 `"relationship"`
- `get_edge(edge_id: str) -> Edge | None` — 按边 ID 查询
- `get_edges_between(source_id: str, target_id: str) -> list[Edge]` — 查两节点间所有边
- `delete_edge(edge_id: str) -> None` — 按边 ID 删除
- `update_edge_type(edge_id: str, edge_type: str, label: str) -> None` — 修改边类型和标签（用于降级）

**查询：**
- `get_neighbors(node_id: str) -> list[Node]` — 仅返回 `edge_type="neighbor"` 的出邻居
- `get_all_neighbors(node_id: str) -> list[Node]` — 返回所有类型的出邻居（含关系边目标）
- `get_relationship_edges(source_ids: list[str], target_ids: list[str]) -> list[Edge]` — 查两组节点间的关系边（双向：source→target 和 target→source）
- `get_out_edges(node_id: str, edge_type: str | None = None) -> list[Edge]` — 返回出边（可按类型过滤）
- `get_subgraph(node_id: str, token_budget: TokenBudget | None = None) -> Subgraph`
- `get_all_nodes() -> list[Node]`
- `get_all_edges() -> list[Edge]`

**持久化钩子：**
- `save() -> None`
- `load() -> None`
- `commit() -> None`
- `save_full() -> None`

所有边一律为单向 `source→target`；系统 MUST NOT 提供 `bidirectional` 边类型或 `direction` 参数。

#### Scenario: 消费者依赖统一接口

- **WHEN** `QueryEngine` 或 `WritePipeline` 初始化接收 store 参数
- **THEN** 参数类型 MUST 为 `StoreInterface`

#### Scenario: add_edge 默认为邻居边

- **WHEN** 调用 `add_edge(a, b)` 不指定 edge_type
- **THEN** MUST 创建 `edge_type="neighbor"`, `label=""` 的边

#### Scenario: add_edge 创建关系边

- **WHEN** 调用 `add_edge(a, b, edge_type="relationship", label="涉及")`
- **THEN** MUST 创建带 label 的关系边

#### Scenario: get_neighbors 只返回邻居边

- **WHEN** 节点 A 同时有邻居边到 B 和关系边到 C
- **THEN** `get_neighbors(A)` MUST 只返回 B，MUST NOT 返回 C

#### Scenario: get_relationship_edges 双向查询

- **WHEN** 调用 `get_relationship_edges([A], [B])`
- **THEN** MUST 返回 A→B 和 B→A 方向的所有关系边

#### Scenario: 同一对节点多条边

- **WHEN** 节点 A 和 B 之间有一条邻居边和两条关系边（label 不同）
- **THEN** `get_edges_between(A, B)` MUST 返回 3 条边

---

### Requirement: 边持久化支持类型和标签

SQLite 边表 schema MUST 包含 `id`, `source_id`, `target_id`, `edge_type`, `label` 列。PRIMARY KEY 为 `id`。MUST 在 `source_id` 和 `target_id` 上建索引。`save_full` / `load` round-trip MUST 逐条保真（含 edge_type 和 label）。

#### Scenario: 边表包含 edge_type 和 label 列

- **WHEN** 建表或落库边
- **THEN** 边记录 MUST 含 `(id, source_id, target_id, edge_type, label)`

#### Scenario: round-trip 保真

- **WHEN** 含邻居边和关系边的图 `save_full` 后 `load`
- **THEN** 加载的边集合 MUST 与落库前逐条一致（含 edge_type 和 label）

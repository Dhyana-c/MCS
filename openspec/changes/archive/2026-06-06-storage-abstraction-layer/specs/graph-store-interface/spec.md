## ADDED Requirements

### Requirement: GraphStoreInterface 定义图操作抽象基类

系统 SHALL 定义 `GraphStoreInterface` 为 `abc.ABC`，提供以下抽象方法：

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
- `get_all_nodes(self) -> list[Node]`
- `get_all_edges(self) -> list[Edge]`

#### Scenario: 消费者依赖接口而非实现

- **WHEN** `QueryEngine` 或 `WritePipeline` 初始化接收 graph 参数
- **THEN** 参数类型 MUST 为 `GraphStoreInterface`，不依赖具体实现类

#### Scenario: 实现类必须继承 ABC

- **WHEN** 创建新的图存储后端（如 SQLiteGraphStore）
- **THEN** MUST 继承 `GraphStoreInterface` 并实现全部抽象方法

---

### Requirement: InMemoryGraphStore 实现 GraphStoreInterface

系统 SHALL 提供 `InMemoryGraphStore` 作为 `GraphStoreInterface` 的默认实现，使用 `dict` 存储节点/边/邻接关系。

#### Scenario: 功能等价于旧 GraphStore

- **WHEN** 将旧 `GraphStore` 替换为 `InMemoryGraphStore`
- **THEN** 所有方法的行为 MUST 与旧实现完全一致

---

### Requirement: 向后兼容别名

系统 SHALL 提供 `GraphStore = InMemoryGraphStore` 别名，保持向后兼容。

#### Scenario: 旧代码仍可使用 GraphStore

- **WHEN** 代码中 `from mcs.core.graph import GraphStore`
- **THEN** MUST 获得与 `InMemoryGraphStore` 相同的类

---

### Requirement: StorageInterface 接收 GraphStoreInterface

`StorageInterface` 的 `save` 和 `save_full` 方法参数类型 SHALL 更新为 `GraphStoreInterface`。

#### Scenario: StorageInterface 与存储后端解耦

- **WHEN** `SQLiteStoragePlugin.save(graph)` 被调用
- **THEN** `graph` 参数类型 MUST 为 `GraphStoreInterface`

---

### Requirement: PluginContext.graph 类型为 GraphStoreInterface

`PluginContext.graph` 的类型标注 SHALL 为 `GraphStoreInterface`。

#### Scenario: 插件通过接口访问图

- **WHEN** 插件通过 `context.graph` 访问图
- **THEN** 类型 MUST 为 `GraphStoreInterface`
## MODIFIED Requirements

### Requirement: query 默认返回 Subgraph

`QueryEngine.query()` SHALL 默认返回 `Subgraph`（`nodes` + `edges`），复用 `core/graph.py` 既有 `Subgraph` 定义。`edges` MUST 仅含被选中的**关系边**、MUST NOT 含层级边：**`property_graph` 模式**为事实边（`kind="fact"`），**`attribute_node` 模式**为无类型关联边（`kind="assoc"`）。期望 `List[Node]` 的后置插件 MUST 经兼容层接收 `subgraph.nodes`；合成自然语言仍由后置插件可选提供。

#### Scenario: 返回 Subgraph

- **WHEN** 后置处理链为空
- **THEN** `query()` MUST 返回 `Subgraph`，`nodes` 为累积节点，`edges` 为选中的关系边

#### Scenario: edges 只含关系边、不含层级边

- **WHEN** 检查返回的 `Subgraph.edges`
- **THEN** `property_graph` 模式所有边 `kind` MUST 为 `"fact"`；`attribute_node` 模式 MUST 为 `"assoc"`；两模式 MUST NOT 含层级边

#### Scenario: 后置插件兼容 List[Node]

- **WHEN** 后置链含期望 `List[Node]` 的旧插件
- **THEN** 框架 MUST 从 `Subgraph.nodes` 提取节点列表传入

## ADDED Requirements

### Requirement: attribute_node 模式活跃视图取关联边

`attribute_node` 模式下，阶段 ③ 事实 BFS 构建活跃视图时 SHALL 以 `get_assoc(node)` 取代 `get_facts(node)`：视图 = {层级邻居 + 关联边 + 关联端点（含属性节点）}。`select_facts` 选中关联边后，其端点 MUST 补入 `accumulated`。遍历的其余机制（visited、安全阀、分层分批、批量 + 逐节点回退、未选中可重发现）MUST 与 `property_graph` 模式一致。`property_graph` 模式仍用 `get_facts`（见「语义理解 Loop 使用 select_facts 筛选候选」）。

#### Scenario: 活跃视图取 assoc

- **WHEN** `attribute_node` 模式 BFS 访问节点 A
- **THEN** 框架 MUST 用 `get_assoc(A)` 构建视图（含属性节点端点），MUST NOT 依赖 `get_facts(A)`

#### Scenario: 选中关联边补入端点

- **WHEN** `attribute_node` 模式 LLM 选中一条关联边 `(A, B)` 而 A 或 B 未被直接选中
- **THEN** 框架 MUST 把 A、B 加入 `accumulated`

#### Scenario: 遍历机制与 property_graph 一致

- **WHEN** `attribute_node` 模式遍历
- **THEN** visited / 安全阀 / 分层分批 / 批量回退行为 MUST 与 `property_graph` 模式逐项一致，仅关系边来源不同

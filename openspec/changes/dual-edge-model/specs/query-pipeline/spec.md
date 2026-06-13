## ADDED Requirements

### Requirement: 种子定位输出为 Subgraph

种子定位（阶段 ②）完成后，MUST 查询所有种子之间的关系边，以 `Subgraph` 形式输出（nodes + edges）。种子间的关系边为后续 BFS 提供初始语义上下文。

#### Scenario: 种子间关系边包含在输出中

- **WHEN** 种子定位找到种子 [A, B, C]，且 A↔B 之间存在关系边
- **THEN** 输出的 `Subgraph.edges` MUST 包含 A↔B 的关系边

#### Scenario: 种子间无关系边时 edges 为空

- **WHEN** 种子定位找到种子 [A, B]，且 A 和 B 之间无关系边
- **THEN** 输出的 `Subgraph.edges` MUST 为空列表

---

## MODIFIED Requirements

### Requirement: 语义理解 Loop 使用选事实机制筛选候选

Within stage ③, the framework MUST issue LLM calls with `purpose = select_facts` to filter frontier facts. 候选节点和浮现的关系边 MUST 统一编号平铺为事实条目列表，LLM 直接选事实（可选手节点和/或边）。The calls SHALL use batch expansion strategy: multiple frontier nodes and their neighbors can be combined into a single LLM call as long as total tokens ≤ budget.

#### Scenario: 批量扩展减少 LLM 调用次数

- **WHEN** multiple frontier nodes have neighbors that fit within token budget when combined
- **THEN** framework MUST issue ONE LLM call for the batch instead of one call per frontier node

#### Scenario: 候选节点和关系边统一编号平铺

- **WHEN** BFS 扩展产生候选节点集 C，且已选节点集 S 与 C 之间存在关系边 E
- **THEN** framework MUST 将 C 中的节点和 E 中的关系边统一编号（①②③...）平铺为事实条目列表渲染给 LLM

#### Scenario: LLM 选中事实条目

- **WHEN** LLM 返回选中的事实编号列表（如 `[1, 3, 4]`）
- **THEN** 框架 MUST 解析编号：编号对应节点 → 加入 `accumulated` 和 `visited`；编号对应边 → 加入 `result_edges`

#### Scenario: 选中边时端点节点自动补入

- **WHEN** LLM 选中了一条关系边 (A, label, B)，但 A 或 B 未被直接选中
- **THEN** 框架 MUST 自动将 A 和 B 加入 `accumulated` 和 `visited`

#### Scenario: 同一对节点间多条边作为独立事实

- **WHEN** 候选中节点 A 和已选节点 S 之间存在多条关系边（label 不同）
- **THEN** 每条边 MUST 作为独立的事实条目（独立编号），LLM 可以分别选中或跳过

#### Scenario: 未选中邻居可被后续轮次重新发现

- **WHEN** LLM does not select a neighbor candidate
- **THEN** that neighbor MUST NOT be added to `visited`; subsequent rounds MAY rediscover it via other paths

#### Scenario: 批量超预算时拆分或逐节点处理

- **WHEN** combined batch would exceed `token_budget.T`
- **THEN** framework MUST either split into smaller batches or fallback to single-node processing

---

### Requirement: query 默认返回 Subgraph 而非纯节点集

The system SHALL default `QueryEngine.query()` to return `Subgraph` (containing `nodes: list[Node]` and `edges: list[Edge]`). The `edges` field MUST only contain `relationship` type edges (neighbor edges are structural and not included). Post-processing plugins that expect `List[Node]` MUST receive `subgraph.nodes` via compatibility layer.

#### Scenario: 未配置后置插件时返回 Subgraph

- **WHEN** 后置处理链为空
- **THEN** `query()` MUST 返回 `Subgraph` 实例，其 `nodes` 为仲裁后的节点集，`edges` 为 BFS 过程中选中的关系边

#### Scenario: 后置插件兼容 List[Node]

- **WHEN** 后置处理链含一个期望 `List[Node]` 输入的旧插件
- **THEN** 框架 MUST 从 `Subgraph.nodes` 提取节点列表传入该插件

#### Scenario: Subgraph.edges 只含关系边

- **WHEN** 检查返回的 Subgraph.edges
- **THEN** 所有边的 `edge_type` MUST 为 `"relationship"`，MUST NOT 含邻居边

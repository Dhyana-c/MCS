## MODIFIED Requirements

### Requirement: 语义理解 Loop 使用 select_nodes 篮选候选

Within stage ③, for each round, the framework MUST issue LLM calls with `purpose = select_nodes` to filter frontier nodes. The calls SHALL use batch expansion strategy: multiple frontier nodes and their neighbors can be combined into a single LLM call as long as total tokens ≤ budget.

#### Scenario: 批量扩展减少 LLM 调用次数

- **WHEN** multiple frontier nodes have neighbors that fit within token budget when combined
- **THEN** framework MUST issue ONE LLM call for the batch instead of one call per frontier node

#### Scenario: 仅选中邻居节点加入 accumulated 和 visited

- **WHEN** LLM returns selected node IDs from batch expansion
- **THEN** selected neighbor nodes MUST be added to `accumulated` and `visited`; center nodes MUST NOT be added (they are already visited); unselected neighbors MUST NOT be added to `visited`

#### Scenario: 未选中邻居可被后续轮次重新发现

- **WHEN** LLM does not select a neighbor candidate
- **THEN** that neighbor MUST NOT be added to `visited`; subsequent rounds MAY rediscover it via other paths

#### Scenario: 批量超预算时拆分或逐节点处理

- **WHEN** combined batch would exceed `token_budget.T`
- **THEN** framework MUST either split into smaller batches or fallback to single-node processing
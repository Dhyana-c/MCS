## MODIFIED Requirements

### Requirement: _traverse 删除 max_picked 参数，改用 token 预算控制

The system SHALL modify `QueryEngine._traverse` to remove `max_picked` parameter and use `token_budget.T` as the termination condition. In batch expansion mode, the packing threshold SHALL be `token_budget.T * 0.8` to reserve margin for estimation errors.

#### Scenario: 不再依赖节点计数

- **WHEN** checking `_traverse` implementation
- **THEN** code MUST NOT contain `len(accumulated) >= max_picked` logic

#### Scenario: token 预算作为终止条件

- **WHEN** `accumulated` estimated token sum > `token_budget.T`
- **THEN** traversal MUST terminate immediately

#### Scenario: 批量打包使用 80% 预算阈值

- **WHEN** packing multiple centers into a batch
- **THEN** the framework MUST stop packing when `batch_tokens >= token_budget.T * 0.8`

---

### Requirement: 遍历流程实现用户定义的语义

The system SHALL implement `_traverse` with batch expansion. The flow is:

1. Initialize: `accumulated = []`, `visited = set()`, `queue = [(seed, 0)]`
2. Pack batch: greedily take nodes from queue until `batch_tokens >= T * 0.8`
3. Load neighbors for each center in the batch, maintaining `neighbor_to_center` mapping
4. LLM filter: `selected_ids = llm.select_nodes([*centers, *all_neighbors], query, accumulated)`
5. For each selected neighbor: if not visited, add to `accumulated` and `visited`, enqueue with `depth = parent_center_depth + 1`
6. If `accumulated` token > budget → terminate
7. Repeat steps 2-6 until queue empty or budget exceeded

#### Scenario: 完整遍历流程

- **WHEN** calling `_traverse(seeds, query, ctx)`
- **THEN** framework MUST follow the above batch expansion flow

#### Scenario: 每轮后检查预算

- **WHEN** a batch expansion completes, new nodes added to `accumulated`
- **THEN** framework MUST compute current `accumulated` token sum; if > `token_budget.T`, terminate

#### Scenario: 邻居-中心映射正确维护

- **WHEN** loading neighbors for batch centers
- **THEN** framework MUST maintain `neighbor_id -> (center_id, center_depth)` mapping for depth calculation
## MODIFIED Requirements

### Requirement: _traverse 删除 max_picked 参数，改用 token 预算控制

The system SHALL modify `QueryEngine._traverse` to remove `max_picked` parameter and use `token_budget.T` as the termination condition. In batch expansion mode, the packing threshold SHALL be `token_budget.T * 0.8` to reserve margin for estimation errors. The `used_tokens` variable SHALL be maintained incrementally — incremented when nodes are added to `accumulated` — rather than recomputed from scratch each iteration.

#### Scenario: 不再依赖节点计数

- **WHEN** 检查 `_traverse` 实现
- **THEN** 代码 MUST NOT 包含 `len(accumulated) >= max_picked` 逻辑

#### Scenario: token 预算作为终止条件

- **WHEN** `used_tokens` (incrementally maintained) > `token_budget.T`
- **THEN** 遍历 MUST 立即终止

#### Scenario: 批量打包使用 80% 预算阈值

- **WHEN** packing multiple centers into a batch
- **THEN** the framework MUST stop packing when `batch_tokens >= token_budget.T * 0.8`

#### Scenario: used_tokens 增量累加

- **WHEN** 检查 `_traverse` 的 while 循环体
- **THEN** `used_tokens` MUST 仅在节点加入 `accumulated` 时递增；MUST NOT 包含 `sum(estimate_node(n) for n in accumulated)` 全量重算

#### Scenario: 批量打包 token 估算去重

- **WHEN** 打包多个中心节点到同一批次，且中心 A 和中心 B 共享邻居 X
- **THEN** X 的 token MUST 仅计入批次一次（在 X 首次加入 batch_neighbors 时），MUST NOT 重复计入每个中心节点的 neighbor_tokens

---

### Requirement: 遍历流程实现用户定义的语义

The system SHALL implement `_traverse` with batch expansion. The flow is:

1. Initialize: `accumulated = []`, `visited = set()`, `queue = deque([(seed, 0)])`, `used_tokens = 0`, `estimate_cache = {}`
2. Pack batch: greedily take nodes from queue until `batch_tokens >= T * 0.8`. Shared neighbors across centers MUST be counted only once in batch_tokens estimation.
3. Load neighbors for each center in the batch, maintaining `neighbor_to_center` mapping. Use `{id: node}` dict for O(1) lookup instead of linear scan.
4. LLM filter: `selected_ids = llm.call(purpose="select_nodes_batch", nodes_in=[*centers, *all_neighbors], query, accumulated)`
5. For each selected neighbor: if not visited, add to `accumulated` and `visited`, increment `used_tokens += estimate_node(node, estimate_cache)`, enqueue with `depth = parent_center_depth + 1`
6. If `used_tokens > budget` → terminate
7. Repeat steps 2-6 until queue empty or budget exceeded

#### Scenario: 完整遍历流程

- **WHEN** 调用 `_traverse(seeds, query, ctx)`
- **THEN** 框架 MUST 按上述批量扩展流程执行

#### Scenario: 每轮后检查预算

- **WHEN** 一轮批量扩展完成，新节点加入 `accumulated`
- **THEN** 框架 MUST 检查增量维护的 `used_tokens`；若 > `token_budget.T`，终止遍历

#### Scenario: 邻居-中心映射正确维护

- **WHEN** loading neighbors for batch centers
- **THEN** framework MUST maintain `neighbor_id -> (center_id, center_depth)` mapping for depth calculation

#### Scenario: queue 使用 deque

- **WHEN** 检查 `_traverse` 的 queue 变量
- **THEN** MUST 为 `collections.deque` 类型，MUST 使用 `popleft()` / `appendleft()` 替代 `pop(0)` / `insert(0, ...)`

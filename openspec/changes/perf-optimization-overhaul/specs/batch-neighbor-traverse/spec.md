## MODIFIED Requirements

### Requirement: _traverse 采用批量邻居扩展策略

The system SHALL modify `QueryEngine._traverse` to use batch neighbor expansion. Instead of processing one node at a time, multiple nodes from the queue SHALL be packed together and their neighbors sent to LLM in a single call, as long as the total token count does not exceed the budget. The implementation SHALL use `collections.deque` for the queue, `{id: node}` dict for neighbor lookup, and reuse a single `ContextRenderer` instance across all batches within the same traversal.

#### Scenario: 批量打包从 queue 取多个节点

- **WHEN** `_traverse` processes the queue
- **THEN** the framework MUST greedily pack multiple nodes from the queue until the estimated token count (centers + all unique neighbors) approaches `token_budget.T * 0.8` (80% threshold)

#### Scenario: 单次 LLM 调用覆盖多节点扩展

- **WHEN** a batch of centers and their neighbors is packed
- **THEN** the framework MUST issue ONE `llm.call(purpose="select_nodes_batch", nodes_in=[*centers, *all_neighbors], ...)` call

#### Scenario: 批量调用减少 LLM 次数

- **WHEN** comparing batch mode vs single-node mode for the same traversal
- **THEN** batch mode MUST result in fewer LLM calls (or equal, never more)

#### Scenario: queue 使用 deque 实现

- **WHEN** 检查 `_traverse` 的 queue 变量
- **THEN** MUST 为 `collections.deque`；入队出队 MUST 使用 `popleft()` / `appendleft()`

#### Scenario: neighbor 查找使用 dict

- **WHEN** 从 LLM 返回的 selected_ids 查找对应的 Node 对象
- **THEN** MUST 使用 `{node_id: node}` 字典 O(1) 查找；MUST NOT 使用 `next((n for n in batch_neighbors if n.id == ...), None)` 线性扫描

#### Scenario: ContextRenderer 实例复用

- **WHEN** `_traverse` 执行多轮批量扩展
- **THEN** MUST 在 while 循环外创建一个 `ContextRenderer` 实例并复用；MUST NOT 在每轮/每批内重新创建

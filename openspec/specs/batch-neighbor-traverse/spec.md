# batch-neighbor-traverse Specification

## Purpose
定义批量邻居扩展遍历策略，优化 `_traverse` 阶段的 LLM 调用效率。在 token 预算允许的前提下，将多个节点及其邻居合并后一次 LLM 调用，减少遍历过程中的延迟和成本。

## Requirements

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

---

### Requirement: 批量扩展保持 BFS 深度语义正确

The system SHALL maintain correct BFS depth semantics when processing batched expansions. Each selected neighbor's depth MUST be calculated as `parent_center_depth + 1`.

#### Scenario: 选中邻居深度基于所属中心

- **WHEN** a neighbor is selected from the batch and its parent center has `depth=D`
- **THEN** the neighbor MUST be added to the queue with `depth=D+1`

#### Scenario: 邻居-中心映射维护

- **WHEN** loading neighbors for batched centers
- **THEN** the framework MUST maintain a mapping `neighbor_id -> (center_id, center_depth)` for each neighbor

#### Scenario: 不同深度中心节点可同批处理

- **WHEN** the batch contains centers at different depths (e.g., center_A at depth=2, center_B at depth=3)
- **THEN** their neighbors MUST still be correctly assigned depths based on their respective parents

---

### Requirement: 批量调用失败时回退到逐节点处理

The system SHALL fallback to single-node processing when batch LLM call fails (e.g., parse error, timeout). This ensures robustness when batch mode encounters issues.

#### Scenario: 解析失败触发回退

- **WHEN** batch LLM call raises `LLMParseError`
- **THEN** the framework MUST fallback to processing each center individually with separate LLM calls

#### Scenario: 回退后结果与批量模式等价

- **WHEN** fallback is triggered
- **THEN** the final `accumulated` result MUST be semantically equivalent to what batch mode would have produced (modulo LLM non-determinism)

---

### Requirement: 批量打包预留预算余量

The system SHALL reserve a 20% margin when packing batches to account for token estimation errors. The packing threshold SHALL be `token_budget.T * 0.8`.

#### Scenario: 打包阈值为 80% 预算

- **WHEN** checking the batch packing condition
- **THEN** the framework MUST stop adding centers when `batch_tokens >= T * 0.8`

#### Scenario: 余量避免超预算

- **WHEN** actual rendering tokens exceed estimation
- **THEN** the 20% margin MUST absorb the error without exceeding `token_budget.T`

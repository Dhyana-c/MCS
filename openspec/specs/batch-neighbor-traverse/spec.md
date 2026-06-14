# batch-neighbor-traverse Specification

## Purpose
定义批量邻居扩展遍历策略，优化 `_traverse` 阶段的 LLM 调用效率。在 token 预算允许的前提下，将多个节点及其邻居合并后一次 LLM 调用，减少遍历过程中的延迟和成本。

## Requirements

### Requirement: _traverse 采用批量邻居扩展策略

`_traverse` MUST 以 `purpose=select_facts` 进行**事实 BFS**：每访问一个节点，渲染其**活跃双向视图**（出事实 + 入事实 + 层级邻居）为统一编号的事实条目供 LLM 选取。多个待扩展节点的视图在总 token ≤ 预算余量内 MAY **合并进一次 LLM 调用**（按层级分批，富余合并）。旧的 `select_nodes` / `select_nodes_batch`（只选节点、不浮现事实）SHALL 被 `select_facts` 取代。

#### Scenario: 批量合并减少调用

- **WHEN** 多个节点的活跃视图合计 ≤ 预算余量
- **THEN** 框架 MUST 合并为一次 `select_facts` 调用，而非每节点一次

#### Scenario: 超预算时按层切分

- **WHEN** 合并视图超过预算
- **THEN** 框架 MUST 按层级切分为更小批次

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

当批量 `select_facts` 调用解析失败时，框架 MUST 回退到**逐节点** `select_facts`（单节点活跃双向视图），保证遍历不因单次批量失败而中断。

#### Scenario: 解析失败逐节点回退

- **WHEN** 批量 `select_facts` 返回无法解析
- **THEN** 框架 MUST 对该批每个节点单独发 `select_facts` 调用

---

### Requirement: 批量打包预留预算余量

The system SHALL reserve a 20% margin when packing batches to account for token estimation errors. The packing threshold SHALL be `token_budget.T * 0.8`.

#### Scenario: 打包阈值为 80% 预算

- **WHEN** checking the batch packing condition
- **THEN** the framework MUST stop adding centers when `batch_tokens >= T * 0.8`

#### Scenario: 余量避免超预算

- **WHEN** actual rendering tokens exceed estimation
- **THEN** the 20% margin MUST absorb the error without exceeding `token_budget.T`

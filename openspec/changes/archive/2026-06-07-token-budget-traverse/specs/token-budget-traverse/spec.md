# token-budget-traverse Specification

## Purpose
定义 token 预算驱动的遍历逻辑，替代基于节点计数的 max_picked 机制。确保遍历过程遵循 MCS 核心不变量（token 预算约束）。

## Requirements

### Requirement: _traverse 删除 max_picked 参数，改用 token 预算控制

The system SHALL modify `QueryEngine._traverse` to remove `max_picked` parameter and use `token_budget.T` as the termination condition.

#### Scenario: 不再依赖节点计数

- **WHEN** 检查 `_traverse` 实现
- **THEN** 代码 MUST NOT 包含 `len(accumulated) >= max_picked` 逻辑

#### Scenario: token 预算作为终止条件

- **WHEN** `accumulated` 的估算 token 总和 > `token_budget.T`
- **THEN** 遍历 MUST 立即终止

---

### Requirement: accumulated 初始为空，种子经 LLM 筛选后才加入

The system SHALL modify `_traverse` to initialize `accumulated` as empty list. Seeds MUST NOT be pre-populated into `accumulated`; only LLM-selected nodes are added.

#### Scenario: accumulated 初始化为空

- **WHEN** `_traverse` 初始化
- **THEN** `accumulated` MUST 初始化为空列表，而非包含所有 seeds

#### Scenario: LLM 筛选种子

- **WHEN** 新一轮 BFS 开始
- **THEN** 框架 MUST 调用 LLM（purpose="select_nodes"）筛选当前 frontier 中的相关节点

#### Scenario: 选中节点加入 accumulated

- **WHEN** LLM 返回选中的节点 ID 列表
- **THEN** 框架 MUST 将选中节点加入 `accumulated`；未选中的节点不加入

#### Scenario: 无选中节点则终止

- **WHEN** LLM 返回空选择
- **THEN** 遍历 MUST 立即终止，返回当前 `accumulated`

---

### Requirement: visited 语义精确化——仅选中者加入

The system SHALL modify `_traverse` so that only LLM-selected nodes are added to `visited`. Unselected candidates MUST NOT be added to `visited`, allowing them to be rediscovered in subsequent rounds.

#### Scenario: 选中节点加入 visited

- **WHEN** LLM 选中某节点
- **THEN** 该节点 MUST 被加入 `visited` 和 `accumulated`

#### Scenario: 未选中节点不加 visited

- **WHEN** LLM 未选中某候选节点
- **THEN** 该节点 MUST NOT 被加入 `visited`；后续轮次 MAY 重新发现该节点

#### Scenario: visited 防止重复处理

- **WHEN** 某节点已在 `visited` 中
- **THEN** 该节点 MUST NOT 再次被加入 `accumulated` 或出现在 `frontier` 中

---

### Requirement: 遍历流程实现用户定义的语义

The system SHALL implement `_traverse` according to the following flow:

1. 初始化：`accumulated = []`, `visited = set()`, `frontier = seeds`
2. LLM 筛选 frontier：`selected = llm.select_nodes(frontier, query, accumulated)`
3. 若 selected 为空 → 终止
4. 将 selected 加入 accumulated 和 visited
5. 若 accumulated token > budget → 终止
6. 获取 selected 的子节点 → 过滤 visited → 作为新 frontier
7. 重复步骤 2-6 直到无新 frontier 或超预算

#### Scenario: 完整遍历流程

- **WHEN** 调用 `_traverse(seeds, query, ctx)`
- **THEN** 框架 MUST 按上述 7 步流程执行

#### Scenario: 每轮后检查预算

- **WHEN** 一轮 BFS 完成，新节点加入 `accumulated`
- **THEN** 框架 MUST 计算当前 `accumulated` 的 token 总和；若 > `token_budget.T`，终止遍历

---

### Requirement: 单轮候选超预算时分批调用 LLM

The system SHALL implement batch LLM calls when a single round's `frontier` exceeds the token budget. Frontier nodes SHALL be split by budget, and each batch processed separately.

#### Scenario: 候选在预算内直接调用

- **WHEN** 单轮 frontier 的估算 token ≤ budget
- **THEN** 框架 MUST 一次性调用 LLM 筛选

#### Scenario: 候选超预算分批调用

- **WHEN** 单轮 frontier 的估算 token > budget
- **THEN** 框架 MUST 将 frontier 按预算分批，逐批调用 LLM 筛选，合并结果

---

### Requirement: 安全阀机制防止估算偏差

The system SHALL enforce `max_rounds` (BFS depth limit) and `max_accumulated_nodes` (hard node count limit) as safety valves against token estimation errors.

#### Scenario: 达到 max_rounds 终止

- **WHEN** BFS 轮数达到 `max_rounds`
- **THEN** 遍历 MUST 终止

#### Scenario: 达到 max_accumulated_nodes 终止

- **WHEN** `accumulated` 节点数达到 `max_accumulated_nodes`
- **THEN** 遍历 MUST 立即终止

#### Scenario: 正常情况安全阀不触发

- **WHEN** token 预算估算正确且图结构正常
- **THEN** 遍历 MUST 由 token 预算或 LLM 自然收敛终止，而非安全阀

---

### Requirement: SeedSelector 和 _traverse 复用同一 LLM purpose

The system SHALL use the same LLM purpose `select_nodes` for both SeedSelectorPlugin and `_traverse` internal LLM calls. The call signature SHALL be consistent: `llm.call(purpose="select_nodes", nodes_in=candidates, free_args={"query": query, "accumulated_summary": ...})`.

#### Scenario: SeedSelector 使用 select_nodes purpose

- **WHEN** SeedSelectorPlugin 调用 LLM 筛选种子
- **THEN** MUST 使用 `purpose="select_nodes"`

#### Scenario: _traverse 使用 select_nodes purpose

- **WHEN** `_traverse` 内部调用 LLM 筛选候选
- **THEN** MUST 使用 `purpose="select_nodes"`

---

### Requirement: QueryEngine.__init__ 删除 max_picked 参数

The system SHALL remove `max_picked` parameter from `QueryEngine.__init__` and add `max_accumulated_nodes` parameter with default value 1000.

#### Scenario: 初始化不再接受 max_picked

- **WHEN** 检查 `QueryEngine.__init__` 签名
- **THEN** 参数列表 MUST NOT 包含 `max_picked`

#### Scenario: 新增 max_accumulated_nodes 参数

- **WHEN** 检查 `QueryEngine.__init__` 签名
- **THEN** 参数列表 MUST 包含 `max_accumulated_nodes: int = 1000`

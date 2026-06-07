# query-pipeline Specification Delta

## ADDED Requirements

### Requirement: 阶段 ② 增加 SeedSelectorPlugin 链

The system SHALL add a SeedSelectorPlugin chain after TrimPlugin in stage ② (种子定位). The chain SHALL execute serially, each plugin's output becoming the next's input.

#### Scenario: 执行顺序为 Entry → Trim → SeedSelector

- **WHEN** 查询管线执行阶段 ②
- **THEN** 执行顺序 MUST 是：EntryPlugin 链（合并）→ TrimPlugin（硬截断）→ SeedSelectorPlugin 链（语义筛选）

#### Scenario: SeedSelector 链可空

- **WHEN** 未配置任何 SeedSelectorPlugin
- **THEN** 框架 MUST 跳过语义筛选，直接返回 TrimPlugin 输出

---

### Requirement: 阶段 ③ 使用 token 预算驱动而非 max_picked

The system SHALL modify stage ③ (语义理解 Loop) to use `token_budget.T` as termination condition, removing `max_picked` parameter.

#### Scenario: token 预算作为终止条件

- **WHEN** `accumulated` 的估算 token 总和 > `token_budget.T`
- **THEN** 遍历 MUST 立即终止

#### Scenario: 不再依赖节点计数

- **WHEN** 检查 `_traverse` 实现
- **THEN** 代码 MUST NOT 包含 `len(accumulated) >= max_picked` 逻辑

---

### Requirement: 阶段 ③ 遍历语义变更

The system SHALL modify stage ③ traverse flow to implement "select before accumulate" semantics:

1. 初始化：`accumulated = []`, `visited = set()`, `frontier = seeds`
2. LLM 筛选 frontier（purpose="select_nodes"）
3. 若筛选结果为空 → 终止
4. 选中节点加入 accumulated 和 visited
5. 若 accumulated token > 预算 → 终止
6. 获取选中节点的子节点 → visited 过滤 → 作为新 frontier
7. 重复步骤 2-6 直到无新 frontier 或超预算

#### Scenario: 种子经筛选后加入 accumulated

- **WHEN** `_traverse` 接收 seeds
- **THEN** 框架 MUST 先通过 LLM 筛选 seeds，筛选结果加入 `accumulated`；seeds 不直接加入 `accumulated`

#### Scenario: accumulated 初始为空

- **WHEN** `_traverse` 初始化
- **THEN** `accumulated` MUST 初始化为空列表

#### Scenario: 仅选中节点加入 visited

- **WHEN** LLM 选中某节点
- **THEN** 该节点 MUST 被加入 `visited`；未选中者 MUST NOT 加入 `visited`

---

## REMOVED Requirements

### Requirement: 语义理解 Loop 的硬上限 max_picked

**Reason**: MCS 核心不变量是 token 预算，节点计数是代理指标。使用 token 预算驱动遍历更符合设计原则。保留 `max_rounds` 和新增 `max_accumulated_nodes` 作为安全阀。

**Migration**: 依赖 `max_picked` 的调用方需改用 token 预算控制。`QueryEngine.__init__` 删除 `max_picked` 参数，新增 `max_accumulated_nodes` 参数（默认 1000）。

#### Scenario: QueryEngine 删除 max_picked 参数

- **WHEN** 检查 `QueryEngine.__init__` 签名
- **THEN** 参数列表 MUST NOT 包含 `max_picked`

## MODIFIED Requirements

### Requirement: 语义理解 Loop 使用 select_facts 筛选候选

阶段 ③ MUST 以**核心 BFS** 进行：每访问一个节点，渲染其**活跃双向视图**（{该节点的 `关联` 邻居（命题 / 概念，两端可达、反查）+ 层级邻居}），以可配置的 `select_purpose` 让 LLM 选相关命题 / 邻居。`_traverse` MUST 接受参数 `select_purpose: str`，**默认 `"select_facts"`**；读路径 `query()` MUST 使用默认值（即宽召回 `select_facts`）。视图收敛：**Phase 2** 按 `priority` 截断 ≤ T；**Phase 1 不截断**。遍历 MUST 按层级分批（不变量保证每层 ≤ T）。**事件默认不进视图**（核心不反查事件），需出处时走按需 `事实 → 事件` 定向查。

#### Scenario: 每节点渲染活跃双向视图

- **WHEN** BFS 访问节点 A
- **THEN** 框架 MUST 渲染 A 的 `关联` 邻居（命题 / 概念）+ 层级邻居供选择，MUST NOT 默认带入连向 A 的事件

#### Scenario: 读路径使用默认 select_facts

- **WHEN** `query()` 进入阶段③ 的事实筛选
- **THEN** 框架 MUST 以 `purpose="select_facts"`（宽召回）调用 LLM；MUST NOT 因调用方不同而改变读侧 purpose

#### Scenario: 筛选 purpose 可由调用方指定

- **WHEN** `_traverse` 被调用且传入 `select_purpose="X"`
- **THEN** 阶段③ 的所有事实筛选 LLM 调用 MUST 使用 `purpose="X"`，MUST NOT 硬编码为 `select_facts`

#### Scenario: 按层分批、富余合并

- **WHEN** 多个待扩展节点的层级包合计 ≤ 预算
- **THEN** 框架 MUST 合并为一次 LLM 调用；超预算则按层切分

#### Scenario: 选中补入端点

- **WHEN** LLM 选中一条命题 / 关联而其端点未被直接选中
- **THEN** 框架 MUST 把端点加入 `accumulated`

#### Scenario: 未选中邻居可被后续轮次重新发现

- **WHEN** LLM 未选中某候选
- **THEN** 该候选 MUST NOT 被加入 `visited`；后续轮次 MAY 经其他路径重新发现

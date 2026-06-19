# query-pipeline（delta）

> 5 段管线结构不变（① 前置 → ② 种子定位 → ③ 语义理解 Loop → ④ 仲裁 → ⑤ 后置）。下列改写到单一模型：核心 BFS 沿 `关联` 边、活跃视图 = 关联邻居（命题 / 概念）+ 层级邻居，删除 `relation_model` 分支与 `kind="fact"/"assoc"` 区分。read-repair（读时收敛）见 `unified-graph-schema`。

## REMOVED Requirements

### Requirement: attribute_node 模式活跃视图取关联边

**原因**：单一模型，不再分模式。活跃视图统一取 `关联` 邻居（含命题节点端点），并入下方 MODIFIED 的「语义理解 Loop」要求。

## MODIFIED Requirements

### Requirement: query 默认返回 Subgraph

`QueryEngine.query()` SHALL 默认返回 `Subgraph`（`nodes` + `edges`）。`edges` MUST 仅含被选中的关系边（`关联` / `互斥`），MUST NOT 含由聚类涌现的层级（组织）边，MUST NOT 按 `relation_model` 分模式。期望 `List[Node]` 的后置插件 MUST 经兼容层接收 `subgraph.nodes`。

#### Scenario: 返回 Subgraph

- **WHEN** 后置处理链为空
- **THEN** `query()` MUST 返回 `Subgraph`，`nodes` 为累积节点，`edges` 为选中的 `关联` / `互斥` 边

#### Scenario: edges 不含层级（组织）边

- **WHEN** 检查返回的 `Subgraph.edges`
- **THEN** MUST 仅含 `关联` / `互斥` 边，MUST NOT 含聚类形成的"组织中心 → 成员"层级边

### Requirement: 语义理解 Loop 使用 select_facts 筛选候选

阶段 ③ MUST 以**核心 BFS** 进行：每访问一个节点，渲染其**活跃双向视图**（{该节点的 `关联` 邻居（命题 / 概念，两端可达、反查）+ 层级邻居}），以 `purpose=select_facts` 让 LLM 选相关命题 / 邻居。视图收敛：**Phase 2** 按 `priority` 截断 ≤ T；**Phase 1 不截断**。遍历 MUST 按层级分批（不变量保证每层 ≤ T）。**事件默认不进视图**（核心不反查事件），需出处时走按需 `事实 → 事件` 定向查。

#### Scenario: 每节点渲染活跃双向视图

- **WHEN** BFS 访问节点 A
- **THEN** 框架 MUST 渲染 A 的 `关联` 邻居（命题 / 概念）+ 层级邻居供选择，MUST NOT 默认带入连向 A 的事件

#### Scenario: 选中补入端点

- **WHEN** LLM 选中一条命题 / 关联而其端点未被直接选中
- **THEN** 框架 MUST 把端点加入 `accumulated`

#### Scenario: 未选中邻居可被后续轮次重新发现

- **WHEN** LLM 未选中某候选
- **THEN** 该候选 MUST NOT 被加入 `visited`；后续轮次 MAY 经其他路径重新发现

### Requirement: 四工作区与预算归属

read（BFS）的工作状态 SHALL 分为四个区，其中**只有前两个（积累区 / 活跃区）进大模型、占用预算**，另两个（`visited` / `frontier`）仅做簿记、不进 LLM：

- **积累区（`accumulated`）**——已确认相关的节点 / 命题，逐轮累积成答案子图；进 LLM、受 `token_budget`（≤ T）封顶。
- **活跃区**——本轮待 LLM 推理 / 筛选的候选（当前节点的活跃视图，渲染 ≤ `T − 积累区`）；进 LLM。
- **`visited`**——已处理节点 id，去重防环；MUST 仅存轻量 id、不渲染、不计 token。
- **`frontier`**——BFS 待扩展节点 id 队列；MUST 仅存轻量 id、不渲染、不计 token。

每轮喂给 LLM 的 = `S` + 查询 + 积累区 + 活跃区 + `R` 余量，整体 ≤ `W`；即 **积累区 + 活跃区 ≤ `T`**。积累区逐轮变大、活跃区空间随之收缩，逼近 `token_budget` 即停。

#### Scenario: 只有积累区与活跃区计 token

- **WHEN** 一轮 BFS 推理
- **THEN** `accumulated` 与活跃区 MUST 进 LLM 并占预算
- **AND** `visited` / `frontier` MUST 仅存轻量 id、MUST NOT 渲染、MUST NOT 计 token

#### Scenario: 积累区 + 活跃区 ≤ T

- **WHEN** 渲染本轮上下文
- **THEN** 积累区 + 活跃区的渲染量 MUST ≤ `T`（活跃区随积累区增长而收缩）
- **AND** 积累区达 `token_budget` 或达 `max_rounds` 时 MUST 停止扩展

### Requirement: entity-anchored 检索，否定由 LLM 现推

检索 MUST 以**实体为锚**——找出该实体经 `关联` 连到的**命题节点**，MUST NOT 按 query 中的谓词过滤。否定 / 极性问题 MUST 由 LLM 在检索回的命题上现推，MUST NOT 以"命题缺失"作否定依据（开放世界，缺命题 ≠ 否定）。

#### Scenario: 极性问题靠矛盾命题

- **WHEN** 问"小明是否讨厌苹果"，图中有命题"小明喜欢苹果"经关联连小明与苹果、无"讨厌"命题
- **THEN** 框架 MUST 检索到"喜欢"命题，由 LLM 据"喜欢 ⊥ 讨厌"答"不讨厌"；MUST NOT 因"无讨厌命题"直接下结论

#### Scenario: 不按谓词过滤

- **WHEN** query 谓词在图中无对应命题
- **THEN** 检索 MUST 仍返回相关实体间的命题（让 LLM 判读），MUST NOT 返回空

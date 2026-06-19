# write-pipeline（delta）

> 7 段管线结构不变（① 前置 → ② 关联节点定位[复用 read] → ③ 概念提取 → ④ 关系判定 → ⑤ 图更新 → ⑥ 压缩判定/守门 → ⑦ 落盘）。下列 4 条改写到单一模型：关系具体化为**命题节点 + 关联边**（谓词落 content），删除 `kind="fact"` label 边与 `relation_model` 分支。事件 / source 走规则入库（不经此 LLM 抽取链，见 `unified-graph-schema`）。

## MODIFIED Requirements

### Requirement: DecisionList 为纯数据，与图更新严格分离

阶段 ④ 输出 MUST 为可序列化的 `DecisionList`；阶段 ⑤ SHALL 原子应用、**无 LLM 调用**。关系 MUST 具体化为**命题（事实）节点**（`node_class=事实`，谓词落其 `content`）+ `关联` 边连其端点；MUST NOT 建带 `label` 的事实边、MUST NOT 按 `relation_model` 分模式。互斥 MUST 表示为两个事实节点间的 `互斥` 边。

#### Scenario: ⑤ 关系建命题节点 + 关联边

- **WHEN** 应用一条关系决策（X 与 Y 有关系"喜欢"）
- **THEN** ⑤ MUST 建 / 复用命题节点（content 含"喜欢"），并连 `X —关联— 命题`、`命题 —关联— Y`
- **AND** MUST NOT 调用 `add_edge(kind="fact")`、MUST NOT 产生带 label 的边

#### Scenario: 图更新阶段无 LLM 调用

- **WHEN** 执行 ⑤
- **THEN** 框架 MUST NOT 在 ⑤ 发起任何 LLM 调用

### Requirement: 阶段 ④ DecisionList 动作类型简化

阶段 ④ `judge_relations` 的**概念级**动作 MUST 限于 `merge` / `create` / `no_op`（`attach_statement` 移除）。关系判定 MUST 产出"建 / 复用命题节点 + 连 `关联` 边（必要时连 `互斥`）"的意图，MUST NOT 产出关系 `label`、MUST NOT 按 `relation_model` 分模式。`merge` 决策的 `aliases_to_add` 字段用于让 LLM 贡献别名。

#### Scenario: 概念动作三选一

- **WHEN** ④ 判定一个概念
- **THEN** DecisionList 对该概念 MUST 取 `merge`（已存在节点 X，含 `aliases_to_add`）/ `create`（新概念）/ `no_op`（不入图）之一

#### Scenario: 关系产命题节点意图、无 label

- **WHEN** ④ 判定两节点有关系
- **THEN** 决策 MUST 表达"建 / 并命题节点 + 连关联边"的意图，MUST NOT 含关系 `label`

### Requirement: 概念提取生成精简自包含描述

阶段 ③ `extract_concepts` 的 prompt MUST 指导 LLM 生成**精简**的自包含**概念**描述：仅含定义 + 短叶子属性，控制在 **lean 基线**（**~24 token**）。关系语义 MUST NOT 写入概念 `content`——关系由**命题（事实）节点**承载（谓词落其 content）。

#### Scenario: 概念 content 精简且不含关系叙述

- **WHEN** `extract_concepts` 提取一个概念
- **THEN** 其 `content` MUST 仅含定义 + 短属性，MUST NOT 含成句关系叙述（关系归命题节点）

### Requirement: root 关联可选——只挂孤儿

挂接 MUST 仅在新节点**与任何既有节点零关联**（无任何 `关联` 边）时，才创建 `__seed_root__ → node` 的 `关联` 边（孤儿之家）。有 ≥1 条关联的节点 MUST NOT 挂 root（经关联可达）。`__seed_root__` 是普通组织中心（hub 标记），其出边 MUST 为 `关联`。

#### Scenario: 有关联不挂 root

- **WHEN** 新节点已与至少一个既有节点建立 `关联` 边
- **THEN** 系统 MUST NOT 为它创建 `root → node` 边

#### Scenario: 零关联挂 root

- **WHEN** 新节点与任何既有节点都无关联
- **THEN** 系统 MUST 创建 `__seed_root__ → node` 的 `关联` 边

# unified-graph-schema Specification

## Purpose
定义 MCS 图模型的统一数据结构与核心机制：4 类节点（概念 / 事实 / 事件 / source）、有向边（仅 关联 / 互斥）、谓词落点、核心 / 事件双层与有界、守门挂在改图操作上。完整、权威设计见 [`docs/graph-model-design.md`](../../docs/graph-model-design.md)；本 spec 固定**机制契约**（SHALL / MUST）。语义关系类型的扩充（因果 / 背书等）为 TBD，按场景演进。

## Requirements

### Requirement: 节点分 4 类，不引入领域 type

系统 SHALL 以 `node_class ∈ {概念, 事实, 事件, source}` 区分节点的结构行为，MUST NOT 引入"人物 / 地点 / 组织"等领域 type 作为节点分类维度。领域身份如确需，SHALL 降级为 `extensions` 软标签。

#### Scenario: 领域身份不进 node_class

- **WHEN** 写入一个人物和一个抽象概念
- **THEN** 两者的 `node_class` 都 MUST 为 `概念`
- **AND** 领域区分 MUST 存于 `extensions`，MUST NOT 成为独立节点类

### Requirement: hub 仅为标记

`hub` SHALL 仅是打在"组织中心"节点上的标记，**只用于反查 / 可观测**，MUST NOT 具有任何算法含义、MUST NOT 作为节点类或 role。渲染给 LLM 时 hub 节点 MUST 与普通节点无异。

#### Scenario: hub 不影响算法与渲染

- **WHEN** 某概念 / 事实成为组织中心、被打上 `hub` 标记
- **THEN** 它在 fanout / 守门 / BFS 中 MUST 与普通节点行为一致
- **AND** 渲染给 LLM 时 MUST NOT 带特殊标记

### Requirement: 谓词落点，事实即节点

事实 SHALL 表示为**命题节点**（`node_class=事实`），关系谓词 MUST 落在其 `content`，MUST NOT 表示为带 label 的事实边。命题节点 MUST 能被事件背书、能与其他事实互斥。

#### Scenario: 关系命题建节点而非 label 边

- **WHEN** 写入"X 喜欢 Y"这类关系命题
- **THEN** MUST 建一个事实节点（content 含谓词"喜欢"），经关联边连 X 与 Y
- **AND** MUST NOT 建带 `label` 的事实边

### Requirement: 边仅 关联 与 互斥，无 kind / label / 层级

`Edge` SHALL 为有向 `source → target + type + extensions`，`type` 当前仅取 `关联` 或 `互斥`。MUST NOT 保留 `kind ∈ {hierarchy, fact, assoc}`、MUST NOT 有开放 `label`、MUST NOT 引入独立"层级"边（组织层级由聚类涌现，用关联边 + hub 标记表达）。新增语义类型 MUST 经登记，MUST NOT 退化为任意开放字符串。

#### Scenario: 边结构与类型受约束

- **WHEN** 构造任意边
- **THEN** 该边 MUST 有 `source` / `target` / `type` / `extensions`
- **AND** `type` MUST ∈ 已登记类型（当前 `关联` / `互斥`）
- **AND** MUST NOT 有 `kind` 字段、MUST NOT 有开放 `label` 字段、MUST NOT 有"层级"边类型

### Requirement: 概念 / 事实靠 LLM，事件 / source 靠规则

概念 / 事实 SHALL 由 LLM 语义抽取产生；事件 / source SHALL 由**规则**产生、MUST NOT 经 LLM。事件 SHALL 按既定结构直接存（输入须符合该结构），系统 MUST NOT 用 LLM 判断"这算不算事件"；source SHALL 按类型切分分类、保真不改写。

#### Scenario: 事件不经 LLM 抽取

- **WHEN** 写入一条结构化事件记录
- **THEN** 系统 MUST 按其结构直接存为事件节点
- **AND** MUST NOT 用 LLM 从散文里"识别事件"
- **AND** 文本中转述的"三年前发生 X" MUST 被抽成带时间属性的**事实**，MUST NOT 盖到用户时间轴成为事件

### Requirement: 核心 / 事件双层，核心不反查事件

系统 SHALL 把图分为**核心图**（概念 + 事实，有界）与**事件层**（事件，不进核心活跃视图）。`事件 → 事实 / 概念` 连接用 `关联` 边，但**载重规则在存储原语级落实**：`get_relations` 对核心节点（`node_class ∈ {概念, 事实}`）MUST 过滤对端为事件的关联边（事件侧 `get_relations` 仍可达核心）——否则"用户 / 我"这类连着海量事件的节点会把全部事件漏回核心、撑爆活跃视图，且会污染 `priority` 截断样本。事件 MUST NOT 进入 fanout 聚类，全量取事件时 SHALL 按时间倒排截断。

#### Scenario: 核心节点不反查事件

- **WHEN** 渲染某核心节点（如"用户"概念）的活跃视图
- **THEN** MUST NOT 包含连向它的事件（核心侧 `get_relations` 已过滤事件边）
- **AND** 需要出处 / 证据时，MAY 走按需的、有界的 `事实 → 事件` 定向查（独立检索步）

#### Scenario: 存储原语级落实载重规则

- **WHEN** 存在 `事件 —关联— 概念` 边
- **THEN** `get_relations(概念)` MUST NOT 含该边；`get_relations(事件)` MUST 含该边
- **AND** 核心节点的 `priority` 截断 MUST 在排除事件边后进行

### Requirement: 守门挂在改图操作上，超 T 聚类，新中心边吸收

守门 SHALL 在**任何改变邻域的操作**后触发——写入 / 连边 / 合并 / 读修复，MUST NOT 仅限写入。受影响节点活跃视图即将超 `T` 时 MUST 触发 `decide_hub` 语义聚类裂变（MUST NOT 用纯图聚类）；聚类对事实 MUST 只重组不合并。新组织中心 H 生成后 SHALL 做**边吸收**：某节点 X 的子节点 ⊇ H 全部成员时，把 `X → 各成员` 替换为 `X → H`。

#### Scenario: 合并也要过守门

- **WHEN** 两节点合并、合并后邻域即将超 `T`
- **THEN** MUST 像写入一样触发守门
- **AND** 超 T MUST 触发聚类裂变；MUST NOT 因为"这是读 / 合并"而跳过守门

#### Scenario: 新中心边吸收

- **WHEN** 聚类生成新组织中心 H（成员集 M）
- **THEN** 对子节点 ⊇ M 的节点 X，MUST 把 `X → 各成员` 改为 `X → H`
- **AND** 该操作 MUST 减少边数、MUST NOT 使任何节点超 T

### Requirement: 互斥为事实间边

两条事实相互排斥时，系统 SHALL 在两个**事实节点**之间连一条 `互斥` 边，MUST NOT 用"边连边"表达（边连不了边——这正是事实需为节点的原因之一）。

#### Scenario: 互斥连两事实

- **WHEN** 事实 A 与事实 B 相互排斥
- **THEN** MUST 在 A、B 之间建一条 `互斥` 边
- **AND** MUST NOT 把互斥表示为某条边的属性或边间连接

### Requirement: 时序走字段不走边，且帧相对

时序 SHALL 用 `timestamp` extension + 查询期排序表达，MUST NOT 用专门时序边。`timestamp` SHALL 归属某"帧"（用户自己的时间轴 / 某 source 的叙述帧），MUST NOT 把转述 / 叙述时间盖到用户时间轴。

#### Scenario: 转述时间不污染用户时间轴

- **WHEN** 写入"我今天读了一本讲三年前故事的书"
- **THEN** 只有"今天读书"MUST 落在用户时间轴（事件）
- **AND** "三年前的故事"MUST 作为核心事实（带叙述时间属性 + 出处），MUST NOT 在用户时间轴上生成"三年前"的事件

### Requirement: 图质量最终收敛（去重 / 合并）

重复的同名 / 同义概念 SHALL 由读写共同触发收敛：创建时对齐、之后被写 / 读触及时（read-repair）、聚类时合并。同名 SHALL 可由字面匹配当场识别，但 MUST NOT 仅凭同名盲并（同名未必同义，需消歧）。事实去重 SHALL 按"同主 · 同宾 · 同说法"对齐；后台维护扫描（dedup）MAY 合并同名字面事实（背书 / 互斥边重挂；互为互斥的两事实 MUST NOT 合并以避免自互斥 / 矛盾塌缩）。**注意**：聚类裂变（见守门 requirement）对事实 MUST 仍只重组不合并——后台去重与聚类是不同操作。完全未被触及 / 聚类的长尾残留 SHALL 由可选的后台维护扫描兜底。

#### Scenario: 读时也可收敛（read-repair）

- **WHEN** 查询的工作集里出现两个同名 / 同义概念节点
- **THEN** MAY 当场合并（合并产生的节点 MUST 过守门）
- **AND** 需消歧 / 合并后超 T 的，MUST 挂起交写 / 维护，MUST NOT 在读路径同步跑 `decide_hub`

### Requirement: 上下文预算 W = S + T + R（两级闸）

上下文窗口 SHALL 划分为 `W = S + T + R`（系统窗口 / 查询窗口 / 结果窗口），`R = T` 为默认、可配置。预算分**两级闸**：

- **`T`（查询窗口 / 单跳闸）**：不变量阈值——任意节点活跃视图 ≤ T；守门聚类裂变把任何超 `T` 的节点拉回 `T` 以内。
- **`token_budget`（累积闸，≤ T）**：一次查询**跨跳累积**的答案子图上限，给积累区封顶；连同 `max_rounds` 让查询停下来。`token_budget ≤ T`。

`type` 作为结构标记 MUST NOT 计入守门 token 估算；守门口径 MUST 与实际渲染逐字一致（估算 == 渲染）。

#### Scenario: type 不计 token、口径一致

- **WHEN** 估算某节点活跃视图的 token
- **THEN** 边的 `type` MUST NOT 计入
- **AND** 估算字段与去重规则 MUST 与实际渲染逐字一致

#### Scenario: 累积答案受 token_budget 封顶

- **WHEN** 查询跨跳累积的答案子图（积累区）增长
- **THEN** 积累区 MUST 受 `token_budget`（≤ T）封顶
- **AND** 达 `token_budget` 或 `max_rounds` 时查询 MUST 停止扩展
- **AND** 单跳活跃视图 MUST 仍独立受 `T` 约束（累积闸不放宽单跳闸）

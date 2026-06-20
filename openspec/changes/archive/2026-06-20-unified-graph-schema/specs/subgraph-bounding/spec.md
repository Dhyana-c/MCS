# subgraph-bounding（delta）

> 单一模型 + 守门挂在改图操作上 + 边吸收。下列两条 requirement 改写到统一模型；其余（token 估计精度、LLM 归纳、name==content 去重、重组净效果、hub 复用=边吸收）不变。

## MODIFIED Requirements

### Requirement: 子图大小由上下文容量约束

**最大上下文子图不变量**：任意节点的**活跃双向视图**渲染量 MUST ≤ 查询窗口 `T`（`W = S + T + R`，`R = T` 默认，见 `unified-graph-schema`）。"有界" MUST 理解为活跃 / 渲染视图有界，MUST NOT 理解为存储有界（存储可保留低 priority 长尾）。

活跃双向视图（**单一模型**）= {该节点的 `关联` 边（两端可达、反查）+ 关联端点（概念 / 命题）+ 由聚类涌现的层级邻居}。**事件不进核心活跃视图**（事件层单向绑入、核心不反查，见 `unified-graph-schema`）。

估算口径 MUST 与 `context_renderer` 实际渲染**逐字一致**（铁律一），MUST NOT 用更少字段 / 近似公式；边的 `type` 作为结构标记 MUST NOT 计入。**含关系边的渲染**（如 `select_facts` 查询视图）估算 MUST 计入 `关联` 边（`主 — 宾`）token；**`decide_hub` 渲染**只有节点、不含关系边，故 fanout 估算只算"中心 + 层级子节点"。

维持机制：

- **守门挂在改图操作上**：写入 / 连边 / 合并 / 读修复后都 MUST 过守门；受影响节点层级邻域渲染即将 > T 时 MUST 经 `decide_hub` 语义归纳（铁律二）聚 hub 收敛，MUST NOT 用纯图聚类。
- **关系侧 / 截断**：入边 / 关联（反查）MUST NOT 被 fanout 聚类（聚不了、且破坏归属）；其 token 有界由 **Phase 2** 查询渲染期按 `priority` 截断兜。
- **Phase 1**：不截断（配置 T 远小于真实窗口 W）。

#### Scenario: 含关系边的渲染场景估算计入关联边 token

- **WHEN** 估算 `select_facts` 查询视图 token（含关系边）
- **THEN** MUST 复用渲染 `关联` 边的同一函数（`主 — 宾`，无 label），MUST NOT 漏算关联边

#### Scenario: fanout 口径不含关系边、type 不计

- **WHEN** 估算 fanout 触发（`decide_hub` 可行性）
- **THEN** MUST 只算"中心 + 层级子节点"，MUST NOT 计入关联边 token、MUST NOT 计入边 `type`

#### Scenario: 守门挂在改图操作上（含合并）

- **WHEN** 写入 / 连边 / **合并** / 读修复后某节点层级邻域即将 > T
- **THEN** MUST 触发 `decide_hub` 语义归纳收敛；MUST NOT 因"这是读 / 合并"而跳过守门

#### Scenario: 有界指活跃视图非存储

- **WHEN** 节点 A 在存储中有上千条关联边
- **THEN** 不变量 MUST 仅约束渲染出的活跃视图；存储长尾 MUST NOT 视为违反不变量

#### Scenario: Phase 1 不截断、依赖窗口余量

- **WHEN** Phase 1 下某节点活跃视图超过配置 T 但仍 ≤ 真实窗口 W
- **THEN** 系统 MUST NOT 在 Phase 1 截断或报错；截断为 Phase 2 行为

### Requirement: 一次聚类产出多个社区（一进多出）

当节点**层级扇出**触发归纳时，`decide_hub` 的输入 MUST 为中心点 + 其**全部层级子节点**，输出 MUST 允许多个社区；系统据此一次性新建 / 提拔多个中间 hub 并分挂，使中心层级扇出一步收敛。重连为 `关联` 边：删 `中心 → 成员`、建 `中心 → hub`、建 `hub → 成员`。**语义边（`互斥` 及未来的背书等）MUST NOT 被此手术波及**——fanout 只动层级组织、聚不了语义关系。

#### Scenario: 一次产出多个 hub

- **WHEN** `decide_hub` 判定出边侧成员可分为 k 个主题社区（k>1）
- **THEN** 系统 MUST 一次性建 / 提拔 k 个 hub 并分挂，中心一步收敛

#### Scenario: 重连为关联边、不动语义边

- **WHEN** 成员 M 被归入 hub H
- **THEN** MUST 删 `中心 → M`、建 `中心 → H` + `H → M`（均 `关联` 边）；M 的 `互斥` 等语义边 MUST NOT 被波及

#### Scenario: 成员可重叠且无遗漏

- **WHEN** LLM 给出社区划分
- **THEN** 成员 MAY 属于多个 hub；未关联成员 MUST 保留在中心下（不丢）；幻觉 id MUST 忽略

### Requirement: 中间概念节点由 LLM 归纳并真正落地

归纳中间概念 SHALL 由 LLM 语义完成（复用 `decide_hub`）——本质是对知识**重组**，结果 SHALL 真正落到图上而非仅打标记。每个社区 SHALL 按优先级重组：① **合并同义**——把旧的同义概念合并为一（**仅概念**，事实不并）；② **找到关键概念**——以社区里的关键概念作组织中心；③ **概括成新概念**——仅当无现成关键概念时，把这组概念概括成一个新概念。概括出的新概念 MUST 有语义内涵、可独立成义，MUST NOT 是空洞聚合标签（如"信息碎片集合"）。重组后一个原始节点 MAY 关联**多个**父（重叠）。组织中心 SHALL 仅以 **`hub` 标记**标识（MUST NOT 用 `role`——已无 role 分类轴）；渲染给 LLM 时与普通节点**同构**（name+content、无特殊标记）。对**事实**节点 MUST 只重组、不合并（合并会断背书 / 互斥）。

#### Scenario: 优先合并 / 找关键概念，概括仅作兜底

- **WHEN** `decide_hub` 为一个社区重组
- **THEN** 系统 SHALL 优先合并同义概念、或找到关键概念作组织中心；仅当无现成关键概念时才概括出新概念

#### Scenario: 概括的新概念必须实质

- **WHEN** `decide_hub` 判定需概括出新概念
- **THEN** 新概念 MUST 有语义内涵、可独立成义；MUST NOT 产出"信息碎片集合 / 综合信息枢纽"等空洞聚合标签

#### Scenario: 归纳必须语义、非纯聚类

- **WHEN** 提取中间概念
- **THEN** 系统 MUST 用 LLM 语义归纳（`decide_hub`）；MUST NOT 用纯图聚类 / 连通分量替代

#### Scenario: 组织中心以 hub 标记标识、对 LLM 同构

- **WHEN** 渲染一个组织中心节点供 LLM 决策
- **THEN** 其渲染 MUST 与普通节点同构（name+content、无特殊标记）；其中心身份 MUST 由 `hub` 标记体现，MUST NOT 由 `role` 体现

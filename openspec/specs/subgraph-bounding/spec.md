# subgraph-bounding Specification

## Purpose
定义最大上下文子图不变量及其维持机制：邻域容量约束、token 估计精度、LLM 语义归纳、一进多出聚类、渲染去重、重组净效果、hub 复用。

## Requirements

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

---

### Requirement: token 估计精度

系统 SHALL 通过单一入口估计文本 token 数；该估计 MUST 与**实际渲染口径一致**——估算邻域大小所用的渲染量，MUST 等于 `context_renderer` 实际产出的渲染量（相同字段、相同去重规则）。估计 SHALL 不显著高估目标语料（如英文），更 MUST NOT 系统性**低估**（如只算 content、漏算 name 或重复字段），否则守门器会漏判、破坏最大上下文子图不变量。SHALL 预留替换为真分词器的接口。

#### Scenario: 估算与渲染同口径

- **WHEN** 守门器估算某节点一跳邻域是否超容量
- **THEN** 其对每个成员的 token 估算 MUST 等于该成员实际渲染时的 token 量（含 name+content、且 name==content 去重等规则一致）；MUST NOT 用更少字段（如仅 content）低估

#### Scenario: 英文估计不再大幅高估

- **WHEN** 估计一段英文文本的 token 数
- **THEN** 估计值 MUST 不显著高于真实 token 数

#### Scenario: 单一入口可替换实现

- **WHEN** 需要更精确的 token 计数
- **THEN** 框架 MUST 允许在不改调用方的前提下替换估计实现（如接入分词器）

---

### Requirement: 中间概念节点由 LLM 归纳并真正落地

归纳中间概念 SHALL 由 LLM 语义完成（复用 `decide_hub`）——本质是对知识**重组**，结果 SHALL 真正落到图上而非仅打标记。每个社区 SHALL 按优先级重组：① **合并同义**——把旧的同义概念合并为一（**仅概念**，事实不并）；② **找到关键概念**——以社区里的关键概念作组织中心；③ **概括成新概念**——仅当无现成关键概念时，把这组概念概括成一个新概念。概括出的新概念 MUST 有语义内涵、可独立成义，MUST NOT 是空洞聚合标签（如"信息碎片集合"）。重组后一个原始节点 MAY 关联**多个**父（重叠）。组织中心 SHALL 仅以 **`hub` 标记**标识（MUST NOT 用 `role`——已无 role 分类轴）；渲染给 LLM 时与普通节点**同构**（name+content、无特殊标记）。对**事实**节点 MUST 只重组、不合并（合并会断背书 / 互斥）。

#### Scenario: 优先合并 / 找关键概念，概括仅作兜底

- **WHEN** `decide_hub` 为一个社区重组
- **THEN** 系统 SHALL 优先合并同义概念、或找到关键概念作组织中心；仅当无现成关键概念时才概括出新概念

#### Scenario: 概括的新概念必须实质

- **WHEN** `decide_hub` 判定需概括出新概念
- **THEN** 新概念 MUST 有语义内涵、可独立成义；MUST NOT 产出"信息碎片集合 / 综合信息枢纽"等空洞聚合标签

#### Scenario: 找到关键概念作组织中心

- **WHEN** 社区里存在一个关键概念（其余概念围绕它）
- **THEN** 系统 SHALL 以它为组织中心、其余概念关联它（重组边），而非另造新节点

#### Scenario: 合并同义概念

- **WHEN** 一个社区内存在同义概念
- **THEN** 系统 MAY 直接合并它们为一个节点（节点数下降），而非另立父

#### Scenario: 归纳必须语义、非纯聚类

- **WHEN** 提取中间概念
- **THEN** 系统 MUST 用 LLM 语义归纳（`decide_hub`）；MUST NOT 用纯图聚类 / 连通分量替代

#### Scenario: 组织中心以 hub 标记标识、对 LLM 同构

- **WHEN** 渲染一个组织中心节点供 LLM 决策
- **THEN** 其渲染 MUST 与普通节点同构（name+content、无特殊标记）；其中心身份 MUST 由 `hub` 标记体现，MUST NOT 由 `role` 体现

---

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

---

### Requirement: 节点渲染 name 与 content 相同时去重

渲染一个节点供 LLM 决策（`decide_hub` / `navigate_hub` 等）时，若其 `name` 与 `content` 文本相同，MUST 只写一份以节省 token；`name` 与 `content` 不同时 MUST 都写出（name + 含义）。该去重规则 MUST 同时作用于**实际渲染**与 **token 估算**（同口径），以维持最大上下文子图不变量的准确性。

#### Scenario: name==content 只渲染一份

- **WHEN** 渲染某节点且其 name 与 content 文本相同
- **THEN** 渲染输出 MUST 只含一份该文本（不重复）；token 估算 MUST 按一份计

#### Scenario: name!=content 两者都写

- **WHEN** 渲染某节点且 name 与 content 不同
- **THEN** 渲染输出 MUST 同时包含 name 与 content；token 估算按两者之和计

---

### Requirement: 重组以降低总量为净效果

聚类裂变 / 重叠 / hub 复用等一切结构重组，其净效果 MUST 是降低图的总 token / 节点 / 边数（或维持不变量收敛所必需）；总量不降反升的重组 MUST NOT 落地。判定"总量是否下降"时，重组前后的 token 估算 MUST 采用**同一口径、同一作用域**——即对被裂变的中心节点的**全邻域**（中心 + 其全部一跳子节点）分别估算重组前 `before` 与重组后 `after`，MUST NOT 用不对等的作用域（如 before 仅算一批、after 算全邻域）比较。聚类允许**重叠**——一个原始节点 MAY 同时属于多个 hub，只要满足总量下降判据。

#### Scenario: before/after 同口径同作用域

- **WHEN** 校验一次重组是否使中心节点邻域总量下降
- **THEN** `before` 与 `after` MUST 都按中心节点的全邻域（中心 + 全部一跳子节点）以同一估算器计算；MUST NOT 让 `before` 只覆盖部分成员而 `after` 覆盖全邻域

#### Scenario: 重叠聚类被允许

- **WHEN** 一个原始概念在语义上同属多个主题社区
- **THEN** 系统 MAY 把它同时挂到多个 hub 之下（不强制硬划分），只要重组后总 token / 节点 / 边数下降

#### Scenario: 无效重组不落地

- **WHEN** 某次重组（造 hub / 重挂 / 吸收）经同口径校验未降低总量
- **THEN** 系统 MUST NOT 落地该重组（MUST 回滚）

---

### Requirement: hub 复用——包含 hub 全部成员的节点改连 hub

一个 hub `H`（成员集合 M）生成后，若图中某节点 `X` 的一跳子节点集合包含 M（M ⊆ children(X)），系统 SHALL 把 `X` 到 M 各成员的直接边替换为单条有向 `X → H`，使 `X` 经 H 间接连到这些成员——减少边数与 `X` 的扇出、复用已有 hub 结构。

#### Scenario: 子节点超集改连 hub

- **WHEN** hub H 的全部成员 M 都是节点 X 的一跳子节点
- **THEN** 系统 MUST 删除 X 到 M 各成员的直接边、新增有向 `X → H`；X 不再直连 M 中成员，而经 H 间接到达

#### Scenario: 部分包含不吸收

- **WHEN** 节点 X 只包含 hub H 的部分成员（M ⊄ children(X)）
- **THEN** 系统 MUST NOT 改连（避免丢失 X 到未包含成员的关系）

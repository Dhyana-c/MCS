## MODIFIED Requirements

### Requirement: 子图大小由上下文容量约束

任何节点的邻域（节点 + 其**全部一跳子节点**）渲染量 MUST ≤ 一个上下文窗口——此即**最大上下文子图不变量**，是系统硬规则。当某节点（含查询虚拟根 `__seed_root__`）的一跳邻域渲染量逼近 / 超过上下文容量时，系统 MUST 触发中间概念归纳（聚类裂变）把邻域收敛回 ≤ 容量。触发阈值 SHALL 由上下文窗口 / token 预算推导（token-aware），MUST NOT 硬编码为固定邻居数。归纳后，图中**每个**节点（含 root 及新建 hub）的一跳邻域 MUST 仍 ≤ 容量（递归直到处处满足）。

#### Scenario: 一跳邻域超容量触发归纳

- **WHEN** 某节点（或查询虚拟根）的一跳邻域渲染 token 逼近 / 超过上下文容量
- **THEN** 系统 MUST 触发归纳，把成员收敛到中间概念节点之下，使该节点一跳邻域回到 ≤ 容量

#### Scenario: 不变量处处成立

- **WHEN** 一轮归纳产出新的中间 hub
- **THEN** 若该 hub 的一跳邻域仍超容量，系统 MUST 继续递归归纳，直到图中**每个**节点的一跳邻域都 ≤ 容量

#### Scenario: 阈值随上下文窗口自适应

- **WHEN** 上下文窗口配置改变（如 8k → 32k）
- **THEN** 可容纳的成员数（触发阈值）MUST 相应变化；MUST NOT 是固定常数

#### Scenario: 不超容量则不归纳

- **WHEN** 一跳邻域渲染量未超过容量
- **THEN** 系统 MUST NOT 触发归纳，成员原样保留

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

### Requirement: 中间概念节点由 LLM 归纳并真正落地

归纳中间概念 SHALL 由 LLM 语义完成（复用 `decide_hub`）——本质是对知识**重组**，结果 SHALL 真正落到图上而非仅打标记。每个社区 SHALL 按优先级重组：① **合并同义**——把旧的同义概念合并为一；② **找到关键概念**（重点）——识别社区里的关键概念，让其余概念关联它、以它为组织中心；③ **概括成新概念**——仅当无现成关键概念时，把这组概念**概括**成一个新概念并与旧概念关联。概括出的新概念 MUST 有语义内涵、可独立成义，MUST NOT 是空洞聚合标签（如"信息碎片集合""涵盖多领域的综合信息节点"）。重组后一个原始节点 MAY 关联**多个**父（重叠）。`role="hub"` SHALL 仅作可观测性标记——渲染给 LLM 时与普通概念节点**同构**（name+content、无特殊标记）；hub 不过是恰好成为组织中心的普通概念。

#### Scenario: 优先合并 / 找关键概念，概括仅作兜底

- **WHEN** `decide_hub` 为一个社区重组
- **THEN** 系统 SHALL 优先合并同义概念、或找到社区里的关键概念作组织中心；仅当无现成关键概念时才概括出新概念

#### Scenario: 概括的新概念必须实质

- **WHEN** `decide_hub` 判定需概括出新概念（无现成关键概念）
- **THEN** 新概念 MUST 有语义内涵、可独立成义（`role="hub"`），并与该组旧概念关联；MUST NOT 产出"信息碎片集合 / 综合信息枢纽"等空洞聚合标签

#### Scenario: 找到关键概念作组织中心

- **WHEN** 社区里存在一个关键概念（其余概念围绕它）
- **THEN** 系统 SHALL 以它为组织中心、其余概念关联它（重组边），而非另造新节点

#### Scenario: 合并同义概念

- **WHEN** 一个社区内存在同义概念
- **THEN** 系统 MAY 直接合并它们为一个节点（节点数下降），而非另立父

#### Scenario: 归纳必须语义、非纯聚类

- **WHEN** 提取中间概念
- **THEN** 系统 MUST 用 LLM 语义归纳（`decide_hub`）；MUST NOT 用纯图聚类 / 连通分量替代语义归纳

#### Scenario: hub 对 LLM 同构

- **WHEN** 渲染一个 `role="hub"` 节点供 LLM 决策
- **THEN** 其渲染 MUST 与普通概念同构（name+content、无 hub 特殊标记）；role 仅用于系统侧识别层级 / 可观测

## ADDED Requirements

### Requirement: 一次聚类产出多个社区（一进多出）

当一个节点的一跳邻域触发归纳时，`decide_hub` 的输入 MUST 为**中心点 + 其全部一跳子节点**（由最大上下文子图不变量保证 ≤ 一个窗口、可一次装入），输出 MUST 允许**多个社区**；系统 MUST 据此**一次性**新建多个中间 hub、把子节点按社区分挂，使中心节点的一跳邻域一步收敛到 ≤ 容量。MUST NOT 退化为每次仅产出一个 hub 的逐轮归纳。

#### Scenario: 全部一跳子节点一起聚

- **WHEN** 某节点一跳邻域超容量、触发归纳
- **THEN** 喂给 `decide_hub` 的成员 MUST 是该节点的**全部**一跳子节点（而非盲目截取的一批）

#### Scenario: 一次产出多个 hub

- **WHEN** `decide_hub` 判定这批成员可分为 k 个主题社区（k>1）
- **THEN** 系统 MUST 一次性新建 k 个中间 hub 并把成员分挂；中心节点归纳后直连这 k 个 hub（一步收敛），MUST NOT 只造 1 个再逐轮拆

#### Scenario: 成员归属可重叠且无遗漏

- **WHEN** LLM 给出社区划分
- **THEN** 每个一跳子节点 MUST 被分配到**至少一个**社区（MAY 同时属于多个 hub）；对无法分类的成员 MUST 有确定性兜底（保留在中心节点下），MUST NOT 静默丢失成员

### Requirement: 节点渲染 name 与 content 相同时去重

渲染一个节点供 LLM 决策（`decide_hub` / `navigate_hub` 等）时，若其 `name` 与 `content` 文本相同，MUST 只写一份以节省 token；`name` 与 `content` 不同时 MUST 都写出（name + 含义）。该去重规则 MUST 同时作用于**实际渲染**与 **token 估算**（同口径），以维持最大上下文子图不变量的准确性。

#### Scenario: name==content 只渲染一份

- **WHEN** 渲染某节点且其 name 与 content 文本相同
- **THEN** 渲染输出 MUST 只含一份该文本（不重复）；token 估算 MUST 按一份计

#### Scenario: name!=content 两者都写

- **WHEN** 渲染某节点且 name 与 content 不同
- **THEN** 渲染输出 MUST 同时包含 name 与 content；token 估算按两者之和计

### Requirement: 重组以降低总量为净效果

聚类裂变 / 重叠 / hub 复用等一切结构重组，其净效果 MUST 是降低图的总 token / 节点 / 边数（或维持不变量收敛所必需）；总量不降反升的重组 MUST NOT 落地。聚类允许**重叠**——一个原始节点 MAY 同时属于多个 hub，只要满足总量下降判据。

#### Scenario: 重叠聚类被允许

- **WHEN** 一个原始概念在语义上同属多个主题社区
- **THEN** 系统 MAY 把它同时挂到多个 hub 之下（不强制硬划分），只要重组后总 token / 节点 / 边数下降

#### Scenario: 无效重组不落地

- **WHEN** 某次重组（造 hub / 重挂 / 吸收）不降低总量
- **THEN** 系统 MUST NOT 落地该重组

### Requirement: hub 复用——包含 hub 全部成员的节点改连 hub

一个 hub `H`（成员集合 M）生成后，若图中某节点 `X` 的一跳子节点集合包含 M（M ⊆ children(X)），系统 SHALL 把 `X` 到 M 各成员的直接边替换为单条有向 `X → H`，使 `X` 经 H 间接连到这些成员——减少边数与 `X` 的扇出、复用已有 hub 结构。

#### Scenario: 子节点超集改连 hub

- **WHEN** hub H 的全部成员 M 都是节点 X 的一跳子节点
- **THEN** 系统 MUST 删除 X 到 M 各成员的直接边、新增有向 `X → H`；X 不再直连 M 中成员，而经 H 间接到达

#### Scenario: 部分包含不吸收

- **WHEN** 节点 X 只包含 hub H 的部分成员（M ⊄ children(X)）
- **THEN** 系统 MUST NOT 改连（避免丢失 X 到未包含成员的关系）

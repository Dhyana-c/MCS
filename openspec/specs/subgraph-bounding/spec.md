# subgraph-bounding Specification

## Purpose
定义最大上下文子图不变量及其维持机制：邻域容量约束、token 估计精度、LLM 语义归纳、一进多出聚类、渲染去重、重组净效果、hub 复用。

## Requirements

### Requirement: 子图大小由上下文容量约束

修订后的**最大上下文子图不变量**：任意节点的**活跃双向视图**的渲染量目标为 ≤ 一个上下文窗口 T。"有界" MUST 理解为**活跃 / 渲染视图有界**，MUST NOT 理解为存储有界（存储可保留低 priority 长尾）。

活跃双向视图的**组成随 `relation_model`**：

- **`property_graph` 模式**（默认）：{该节点为源的事实边 + 该节点为宾的事实边（反查）+ 层级邻居（`kind="hierarchy"` 出边目标）}。
- **`attribute_node` 模式**：{该节点的无类型关联边（`kind="assoc"`，反查）+ 关联端点（含属性节点）+ 层级邻居}。

估算 token 的口径 MUST 与 `context_renderer` 实际渲染**逐字一致**（铁律一），MUST NOT 用更少字段或近似公式。各渲染场景各自同口径：**含关系边的渲染**（如 `select_facts` 查询视图）估算 MUST 计入该模式的关系边 token——`property_graph` 计事实边（`主 —label→ 宾`）、`attribute_node` 计关联边（`主 — 宾`，无 label）；**`decide_hub` 渲染**只有节点、看不到关系边，故 fanout 估算只算"中心 + 层级子节点"、**不含关系边**（两种模式皆然）。

不变量的维持分两层：

- **写入期 fanout（层级口径）**：触发条件为**「中心节点自身 + 其层级子节点」的渲染 token > T**——即 `decide_hub` 能否一窗装下"中心 + 全部层级子节点"的可行性口径（含中心 content、**不含关系边 token**）。decide_hub 输入只有节点、看不到关系边，且 fanout 聚的是层级子节点、**聚不了关系边**，故关系边不进 fanout 触发（`attribute_node` 模式下属性节点作普通子节点参与）。触发时 MUST 经 `decide_hub` 语义归纳（铁律二）聚 hub 使层级扇出收敛。
- **关系侧 / 硬截断（查询渲染期）**：出关系边与入关系边（反查）都 MUST NOT 被 fanout 聚类（fanout 聚不了；入边聚类还会破坏归属语义）。关系边 token 的有界由 **Phase 2** 在查询渲染时按 `priority` 排序、对双向视图**截断**到 ≤ T 兜，不进写入期 fanout。
- **Phase 1**：**不截断**——配置 T 远小于模型真实窗口 W，活跃视图即便超过 T 仍落在 W 内；Phase 1 仅靠出边侧 fanout 组织，入边反查返回全部 / 宽松上限，`priority` 不参与排序。

#### Scenario: 含关系边的渲染场景估算计入关系边 token

- **WHEN** 估算 `select_facts` 查询视图 token（含关系边）
- **THEN** MUST 复用渲染关系边的同一函数——`property_graph` 用 `主 —label→ 宾` 全部字段、`attribute_node` 用 `主 — 宾`（无 label）——MUST NOT 漏算关系边

#### Scenario: fanout 口径不含关系边

- **WHEN** 估算 fanout 触发（`decide_hub` 可行性）
- **THEN** MUST 只算"中心 + 层级子节点"（与 decide_hub 渲染一致），MUST NOT 计入事实边 / 关联边 token

#### Scenario: 活跃视图组成随模式

- **WHEN** 渲染某节点的活跃双向视图
- **THEN** `property_graph` 模式 MUST 用 {事实边 + 层级邻居}；`attribute_node` 模式 MUST 用 {关联边 + 关联端点（含属性节点）+ 层级邻居}

#### Scenario: 有界指活跃视图非存储

- **WHEN** 节点 A 在存储中有上千条事实边 / 关联边
- **THEN** 不变量 MUST 仅约束**渲染出的活跃视图**；存储中的长尾 MUST NOT 被视为违反不变量

#### Scenario: 层级扇出渲染超 T 触发 LLM 归纳

- **WHEN**「A 自身 + A 的层级子节点」渲染 token > T（decide_hub 可行性口径，不含关系边；Phase 1 无截断确会超）
- **THEN** 系统 MUST 经 `decide_hub` 语义归纳聚 hub 使层级扇出收敛 ≤ T；MUST NOT 用纯图聚类替代（铁律二）；关系边（事实边 / 关联边）MUST NOT 被 fanout 波及

#### Scenario: Phase 1 不截断、依赖窗口余量

- **WHEN** Phase 1 下某节点活跃视图超过配置 T 但仍 ≤ 真实窗口 W
- **THEN** 系统 MUST NOT 在 Phase 1 截断或报错；调用照常进行（截断为 Phase 2 行为）

#### Scenario: Phase 2 按 priority 截断硬保证

- **WHEN** Phase 2 启用、渲染某节点活跃视图
- **THEN** 系统 MUST 按 `priority` 降序、对双向视图截断到 ≤ T

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

---

### Requirement: 一次聚类产出多个社区（一进多出）

当节点**层级扇出**触发归纳时，`decide_hub` 的输入 MUST 为中心点 + 其**全部层级子节点**，输出 MUST 允许多个社区；系统据此一次性新建 / 提拔多个中间 hub 并分挂，使中心层级扇出一步收敛。重连为纯下行层级边：删 `中心→成员`、建 `中心→hub`、建 `hub→成员`（无上行边）。事实边（`kind="fact"`）MUST NOT 被此手术波及。

#### Scenario: 一次产出多个 hub

- **WHEN** `decide_hub` 判定出边侧成员可分为 k 个主题社区（k>1）
- **THEN** 系统 MUST 一次性建 / 提拔 k 个 hub 并分挂，中心一步收敛

#### Scenario: 重连为纯下行层级边、不动事实边

- **WHEN** 成员 M 被归入 hub H
- **THEN** MUST 删 `中心→M` 层级边、建 `中心→H` + `H→M` 层级边；M 的事实边 MUST NOT 被波及

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

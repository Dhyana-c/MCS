# attribute-node-model Specification

## Purpose
定义**可切换的关系表示模式**：在默认的 `property_graph`（带 label 事实边）之外，新增 `attribute_node` 模式——关系具体化为**属性节点**（`role="attribute"`，content 持单一简短说法）+ **无类型关联边**（`kind="assoc"`，无 label）。模式由 `MCSConfig.relation_model` 开关选定（建图时定、写入与查询须同模式、混库未定义）。本能力是关系表示的第二模型，与 `dual-edge-model` 并存；铁律一"估算 == 渲染"在本模式内逐字成立（仅口径随模式切换）。

## Requirements

### Requirement: relation_model 模式开关

系统 SHALL 提供 `MCSConfig.relation_model` 开关，取值 `"property_graph"`（默认）或 `"attribute_node"`，决定关系如何表示。默认 `"property_graph"`，其行为 MUST 与本变更前**逐字一致**。模式 MUST 在建图时选定；同一存储库（DB）的写入与查询 MUST 使用同一模式——跨模式混用同库为未定义行为。

#### Scenario: 默认 property_graph 行为不变

- **WHEN** 未设置 `relation_model` 或设为 `"property_graph"`
- **THEN** 写入 / 查询 / 渲染 / 估算 MUST 与本变更前逐字一致（带 label 事实边模型）

#### Scenario: 切换到 attribute_node 模式

- **WHEN** `relation_model="attribute_node"`
- **THEN** 系统 MUST 用无类型关联边 + 属性节点表达关系（见下方各要求），MUST NOT 产生带 label 的 `kind="fact"` 边

#### Scenario: 同库单模式

- **WHEN** 一个 DB 以某模式写入后，又以另一模式查询
- **THEN** 行为为未定义；系统 MUST NOT 承诺跨模式同库的正确性（建图时选定模式是调用方责任）

---

### Requirement: 无类型关联边 kind="assoc"

`attribute_node` 模式 SHALL 引入第三类边 `kind="assoc"`（无类型关联边）：`label` MUST 为空串，仅表达"两概念相关 / 共现"，MUST NOT 表达"怎么相关"（关系语义由属性节点承载）。assoc 边 MUST **两端可达**——一条 assoc 边只存一份，但两端邻接都 MUST 能索引到它（反查）。同一对节点的 assoc 边 MUST 去重（按 `(source, target)`，无 label 可区分）。

#### Scenario: assoc 边无 label

- **WHEN** 创建 `kind="assoc"` 的边
- **THEN** 其 `label` MUST 为空串

#### Scenario: assoc 边两端可达

- **WHEN** 存在 assoc 边 `小明 —assoc— 小明的爱好`
- **THEN** `get_assoc(小明)` 与 `get_assoc(小明的爱好)` MUST 都包含这条边

#### Scenario: assoc 边去重

- **WHEN** 两次写入同一对节点 `(A, B)` 的 assoc 边
- **THEN** 存储 MUST 只保留一条

---

### Requirement: 关系具体化为属性节点（不带版本）

`attribute_node` 模式 SHALL 把关系语义具体化为**属性节点**：`role="attribute"`，`content` 持**单一当前**自然语言说法（**MUST NOT** 带版本列表 / superseded / 出处 / 置信——那是 Phase 2）。属性节点经 assoc 边连接它所关联的**每个概念端点**；纯字面值（不另建节点的值）MAY 内联进属性节点 `content`。属性节点对 LLM MUST **同构于普通概念**（渲染为 name+content，无特殊标记）；`role="attribute"` 仅供系统识别 / 可观测。属性节点 `content`（说法）MUST **简短、受长度上限约束**（量级同 `property_graph` lean 基线或独立配置上限），MUST NOT 写成长篇叙述——否则单个属性节点 token 无界、撑大活跃视图。

#### Scenario: 概念–概念关系建属性节点 + 两条 assoc 边

- **WHEN** `attribute_node` 模式判定概念 A 与概念 B 有关系
- **THEN** 系统 MUST 建一个属性节点 R（`role="attribute"`，content 为该关系说法），并建 `A —assoc— R` 与 `R —assoc— B`；MUST NOT 建 `A —label→ B` 事实边

#### Scenario: 属性节点不带版本

- **WHEN** 同一关系被多次摄入（不同时间 / 出处）
- **THEN** 属性节点 MUST 仅持单一当前说法；MUST NOT 累积版本列表或 superseded 标记（Phase 2 范畴）

#### Scenario: 属性节点对 LLM 同构

- **WHEN** 渲染一个 `role="attribute"` 节点供 LLM 决策
- **THEN** 其渲染 MUST 与普通概念同构（name+content、无特殊标记）

#### Scenario: 属性节点说法受长度上限约束

- **WHEN** 建 / 并属性节点时其说法过长
- **THEN** 系统 MUST 将其压缩 / 截断到配置上限（量级同 `property_graph` lean 基线），MUST NOT 留长篇叙述

---

### Requirement: attribute_node 模式写入产属性节点 + 无类型边

`attribute_node` 模式下，写入管线阶段 ④ `judge_relations` SHALL 走专属 prompt：MUST NOT 产出关系 label，MUST 产出"为关系建 / 并属性节点 + 连无类型边"的决策意图。阶段 ⑤ 应用该决策时 MUST 建属性节点、连 `kind="assoc"` 边。该模式下"关系具体化动作"（复活的 `attach_statement` 或新增 `create_attribute`）MUST 执行此建图，MUST NOT 为 no-op（property_graph 模式仍维持 `attach_statement` 为 no-op，见 `write-pipeline`）。其余阶段（①②③⑥⑦）行为不变。

#### Scenario: judge_relations 专属 prompt 不产 label

- **WHEN** `attribute_node` 模式执行阶段 ④
- **THEN** 决策 MUST NOT 含关系 label 字段；MUST 表达属性节点与其端点

#### Scenario: 阶段 ⑤ 建属性节点 + assoc 边

- **WHEN** `attribute_node` 模式应用一条关系决策
- **THEN** ⑤ MUST 新建 / 复用属性节点并连 `kind="assoc"` 边；MUST NOT 调用 `add_edge(kind="fact")`

---

### Requirement: attribute_node 模式查询遍历无类型边与属性节点

`attribute_node` 模式下，查询阶段 ③ 事实 BFS SHALL 以 `get_assoc` 取代 `get_facts` 构建活跃视图：每访问一节点，渲染其 {层级邻居 + assoc 边 + assoc 端点（含属性节点）}，由 `select_facts` 选择，选中边的端点补入。**entity-anchored 仍成立**——从实体反查 assoc 命中属性节点、读其 content 得关系；极性 / 否定由 LLM 在属性节点说法上现推。遍历机制（分层分批、批量 + 逐节点回退、visited、安全阀）MUST 不变。

#### Scenario: 活跃视图取 assoc 而非 fact

- **WHEN** `attribute_node` 模式 BFS 访问节点 A
- **THEN** 框架 MUST 用 `get_assoc(A)` 构建视图（含属性节点端点），MUST NOT 依赖 `get_facts(A)`

#### Scenario: entity-anchored 经属性节点现推

- **WHEN** 问"小明是否讨厌苹果"，图中有属性节点"小明喜欢苹果"经 assoc 连小明与苹果
- **THEN** 框架 MUST 反查到该属性节点交 LLM 判读；MUST NOT 因"无讨厌关系"直接下结论

---

### Requirement: attribute_node 模式渲染与估算口径（铁律一）

`attribute_node` 模式下，属性节点 SHALL 按节点渲染（复用 `render_node_full`）；assoc 边 SHALL 经 `render_assoc_edge` 渲染为 `主 — 宾`（**无 label**）。活跃视图 token 估算 MUST 复用上述渲染函数（assoc 边复用 `render_assoc_edge`），MUST NOT 用近似公式——铁律一"估算 == 渲染"在本模式内逐字成立。本模式估算 MUST 计 assoc 边 token、MUST NOT 计 label 事实边 token。

#### Scenario: assoc 边渲染无 label

- **WHEN** 渲染 assoc 边 `(小明, 小明的爱好)`
- **THEN** 输出 MUST 为 `小明 — 小明的爱好` 形式，MUST NOT 含 label

#### Scenario: 估算复用渲染函数

- **WHEN** 估算 assoc 边 token
- **THEN** MUST 调用 `render_assoc_edge` 同一函数再计 token，MUST NOT 用近似公式

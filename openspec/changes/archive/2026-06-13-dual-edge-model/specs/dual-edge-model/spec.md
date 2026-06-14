## ADDED Requirements

### Requirement: 全图两类边——层级边与事实边

每条边 SHALL 标注 `kind`：`"hierarchy"` 或 `"fact"`。

- **层级边** `父→子`：`kind="hierarchy"`，**单向、无 label**（`label` MUST 为空串），构成结构骨架，驱动导航下钻；hub 由 `role="hub"` 识别，不依赖边方向。
- **事实边** `主 —谓→ 宾`：`kind="fact"`，**带非空 label**（粗粒度谓词，如"喜欢""涉及""属于"），承载关系语义与极性，并带 `priority` 分。

#### Scenario: 层级边无 label

- **WHEN** 创建 `kind="hierarchy"` 的边
- **THEN** 其 `label` MUST 为空串

#### Scenario: 事实边带非空 label

- **WHEN** 创建 `kind="fact"` 的边
- **THEN** 其 `label` MUST 为非空、1–4 字的粗粒度谓词，MUST NOT 为完整句子

#### Scenario: 同一对节点可有多条事实边

- **WHEN** 节点 A、B 之间存在多种关系
- **THEN** 系统 MUST 允许多条不同 label 的事实边并存

---

### Requirement: 事实边存一份、两端可达（反查）

一条事实边 MUST **只存一份**（保留方向语义 `主→宾`），但**两端的邻接都 MUST 能索引到它**——即从主或从宾都能取到这条事实（反查）。系统 MUST NOT 为同一事实双向对存两条边。

#### Scenario: 从宾端反查命中

- **WHEN** 存在事实边 `小明 —喜欢→ 苹果`，从 `苹果` 取事实
- **THEN** 该事实 MUST 出现在 `苹果` 的事实集合中（作为入边），其原始方向 / label MUST 原样保留

#### Scenario: 不双向对存

- **WHEN** 写入一条事实
- **THEN** 系统 MUST 只新增一条 `kind="fact"` 边，MUST NOT 同时写 `主→宾` 与 `宾→主` 两条

---

### Requirement: 事实边带 priority（为遗忘预留）

每条事实边 SHALL 带 `priority`（activation）分，**初始默认 `0.0`**。**Phase 1** MUST 仅提供该字段（恒为默认值），MUST NOT 用它排序 / 截断、MUST NOT 实现 activation 衰减；**Phase 2** 由 activation 策略赋值，用 `priority` 在查询渲染期排序、对超预算的活跃视图截断，等值时按 recency / id 做确定性 tie-break（赋值与 tie-break 细节属 Phase 2）。任何阶段 MUST NOT 引入"存放装不进活跃视图的长尾事实"的溢出索引。

#### Scenario: Phase 1 只留字段不截断

- **WHEN** Phase 1 下节点事实超出配置 T
- **THEN** 系统 MUST NOT 用 `priority` 排序 / 截断（依赖配置 T 远小于真实窗口）；`priority` 字段 MUST 存在

#### Scenario: Phase 2 按 priority 截断且不删

- **WHEN** Phase 2 下节点事实超出活跃视图预算
- **THEN** 系统 MUST 按 `priority` 降序取 top、截断到 ≤ T；其余 MUST 留在存储（不删）

#### Scenario: 任何阶段不建溢出索引

- **WHEN** 检查实现
- **THEN** MUST NOT 存在与有界图并行、专门承载溢出长尾的检索存储

---

### Requirement: content 精简，关系上事实边，属性升格

节点 `content` MUST 仅含裸定义 + 短叶子属性，控制在 lean 基线（**~24 token**；英文约 100 字符，中文按 token 计、勿用字符数）；关系语义 MUST 以事实边承载，MUST NOT 以成句叙述写入 content。叶子属性（无对外关系的纯值）留 content；一旦某"属性"需与其他事物发生关系，它 MUST 升格为概念节点、关系走事实边。

#### Scenario: 关系不进 content

- **WHEN** 概念 A 与 B 有关系
- **THEN** 系统 MUST 建 `A —label→ B` 事实边，MUST NOT 把关系写成 A 的 content 叙述

#### Scenario: 有对外关系的属性升格

- **WHEN** 某属性值需要再与别的概念关联
- **THEN** 它 MUST 成为概念节点，原关系 MUST 表达为事实边，MUST NOT 留作 content 叶子

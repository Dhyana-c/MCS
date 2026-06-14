## MODIFIED Requirements

### Requirement: 概念提取生成自包含描述

阶段 ③ `extract_concepts` 的 prompt MUST 指导 LLM 生成**精简**的自包含描述：仅含定义 + 短叶子属性，控制在 **lean 基线**（**~24 token**；英文约 100 字符，中文按 token 计）。关系语义 MUST NOT 写入 content（由事实边承载）。

#### Scenario: content 精简且不含关系叙述

- **WHEN** `extract_concepts` 提取概念
- **THEN** `content` MUST 仅含定义 + 短属性，SHOULD NOT 超过 lean 基线，MUST NOT 含成句关系叙述

---

### Requirement: DecisionList 为纯数据，与图更新严格分离

阶段 ④ 输出 MUST 为可序列化的 `DecisionList`；阶段 ⑤ SHALL 原子应用、无 LLM 调用。Decision 的 `edges_to`（到已有节点）与 `edges_to_names`（到同批新概念）MUST 均为 `list[dict]`（含 `target_id` / `target_name` 与 `label`），用于创建 `kind="fact"` 事实边——**一条事实只存一份**（两端索引），MUST NOT 双向对存。⑤ 第二遍按名解析 `edges_to_names` 时，MUST 同样只写**一条带 label** 的事实边，MUST NOT 再落两条对向单向边。

#### Scenario: create 写一条带 label 事实边

- **WHEN** create decision 含 `edges_to=[{"target_id": "X", "label": "喜欢"}]`
- **THEN** ⑤ MUST 创建一条 `(new_node, X, kind="fact", label="喜欢")` 边，MUST NOT 同时写反向副本

#### Scenario: merge 写一条带 label 事实边

- **WHEN** merge decision 含 `edges_to=[{"target_id": "X", "label": "属于"}]`
- **THEN** ⑤ MUST 创建一条 `(merged_node, X, kind="fact", label="属于")` 边

#### Scenario: 篇内关系（edges_to_names）写单条 label 事实边

- **WHEN** 同批新概念 X 与 Y 间有关系 `X —label→ Y`（经 `edges_to_names` 按名解析）
- **THEN** ⑤ 第二遍 MUST 创建一条 `(X, Y, kind="fact", label)` 边，MUST NOT 写 `Y→X` 副本

#### Scenario: 图更新阶段无 LLM 调用

- **WHEN** 执行 ⑤
- **THEN** 框架 MUST NOT 在 ⑤ 发起任何 LLM 调用

---

## ADDED Requirements

### Requirement: root 关联可选——只挂孤儿

挂接 MUST 仅在新概念**与任何既有概念零事实关联**时，才创建 `__seed_root__ → concept` 层级边（孤儿之家）。有 ≥1 条事实关联的概念 MUST NOT 挂 root（经关联可达）。`__seed_root__` MUST 只产层级边、不参与事实边。

#### Scenario: 有关联不挂 root

- **WHEN** 新概念与至少一个既有概念建立了事实边
- **THEN** 系统 MUST NOT 为它创建 `root→concept` 边

#### Scenario: 零关联挂 root

- **WHEN** 新概念与任何既有概念都无事实关联
- **THEN** 系统 MUST 创建 `(__seed_root__, concept, kind="hierarchy", "")` 边

#### Scenario: root 只产层级边

- **WHEN** 任何模块为 `__seed_root__` 创建出边
- **THEN** `kind` MUST 为 `"hierarchy"`，MUST NOT 为事实边

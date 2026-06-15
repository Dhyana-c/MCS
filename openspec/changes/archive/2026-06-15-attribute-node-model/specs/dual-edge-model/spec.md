## MODIFIED Requirements

### Requirement: 全图两类边——层级边与事实边

本要求定义 **`property_graph` 模式**（默认）的边模型；`attribute_node` 模式的边模型（无类型关联边 `kind="assoc"` + 属性节点）见 `attribute-node-model`（权威）。在 `property_graph` 模式下，每条边 SHALL 标注 `kind`：`"hierarchy"` 或 `"fact"`。

- **层级边** `父→子`：`kind="hierarchy"`，**单向、无 label**（`label` MUST 为空串），构成结构骨架，驱动导航下钻；hub 由 `role="hub"` 识别，不依赖边方向。
- **事实边** `主 —谓→ 宾`：`kind="fact"`，**带非空 label**（粗粒度谓词，如"喜欢""涉及""属于"），承载关系语义与极性，并带 `priority` 分。

#### Scenario: 层级边无 label

- **WHEN** （`property_graph` 模式）创建 `kind="hierarchy"` 的边
- **THEN** 其 `label` MUST 为空串

#### Scenario: 事实边带非空 label

- **WHEN** （`property_graph` 模式）创建 `kind="fact"` 的边
- **THEN** 其 `label` MUST 为非空、1–4 字的粗粒度谓词，MUST NOT 为完整句子

#### Scenario: 同一对节点可有多条事实边

- **WHEN** （`property_graph` 模式）节点 A、B 之间存在多种关系
- **THEN** 系统 MUST 允许多条不同 label 的事实边并存

#### Scenario: attribute_node 模式不产 label 事实边

- **WHEN** `relation_model="attribute_node"`
- **THEN** 写入 MUST NOT 产生 `kind="fact"` 带 label 边；关系改由属性节点 + `kind="assoc"` 无类型边表达（见 `attribute-node-model`）

---

### Requirement: content 精简，关系上事实边，属性升格

本要求仅适用 **`property_graph` 模式**；`attribute_node` 模式的节点 content 与属性节点 content 口径见 `attribute-node-model`（属性节点 content 持简短说法、本身即关系载体，不适用"属性升格走事实边"）。`property_graph` 模式下，节点 `content` MUST 仅含裸定义 + 短叶子属性，控制在 lean 基线（**~24 token**；英文约 100 字符，中文按 token 计、勿用字符数）；关系语义 MUST 以事实边承载，MUST NOT 以成句叙述写入 content。叶子属性（无对外关系的纯值）留 content；一旦某"属性"需与其他事物发生关系，它 MUST 升格为概念节点、关系走事实边。

#### Scenario: 关系不进 content

- **WHEN** （`property_graph` 模式）概念 A 与 B 有关系
- **THEN** 系统 MUST 建 `A —label→ B` 事实边，MUST NOT 把关系写成 A 的 content 叙述

#### Scenario: 有对外关系的属性升格

- **WHEN** （`property_graph` 模式）某属性值需要再与别的概念关联
- **THEN** 它 MUST 成为概念节点，原关系 MUST 表达为事实边，MUST NOT 留作 content 叶子

## ADDED Requirements

### Requirement: 边具有类型和标签

每条边 SHALL 携带 `edge_type`（`"neighbor"` 或 `"relationship"`）和 `label`（字符串）属性。邻居边的 `label` MUST 为空串。关系边的 `label` MUST 为非空字符串，描述源节点到目标节点的关系（如"涉及"、"属于"、"导致"）。

#### Scenario: 邻居边无 label

- **WHEN** 创建一条 `edge_type="neighbor"` 的边
- **THEN** 其 `label` MUST 为空串 `""`

#### Scenario: 关系边有 label

- **WHEN** 创建一条 `edge_type="relationship"` 的边
- **THEN** 其 `label` MUST 为非空字符串

#### Scenario: 同一对节点可有多条边

- **WHEN** 节点 A 和 B 之间已有一条邻居边
- **THEN** 系统 MUST 允许再添加一条或多条关系边（不同 label）

---

### Requirement: seed_root 只产出邻居边

`__seed_root__` 到任意节点的边 MUST 为 `edge_type="neighbor"`。seed_root 不参与任何关系边。

#### Scenario: root 出边始终为邻居边

- **WHEN** 任何模块为 `__seed_root__` 创建出边
- **THEN** `edge_type` MUST 为 `"neighbor"`，`label` MUST 为空串

#### Scenario: root 不作为关系边的端点

- **WHEN** `judge_relations` 或其他模块尝试创建以 `__seed_root__` 为 source 或 target 的关系边
- **THEN** 系统 MUST 将其改为邻居边或拒绝创建

---

### Requirement: hub 与普通概念在边上同权

hub 节点（`role="hub"`）与普通概念节点（`role="concept"`）在关系边上 MUST 一视同仁——hub 可以拥有到任意其他节点的带 label 关系边，边类型和 label 规则与普通概念完全相同。

#### Scenario: hub 拥有关系边

- **WHEN** hub 节点 H 与概念节点 C 之间存在语义关系
- **THEN** 系统 MUST 允许创建 `(H, relationship, label)` 边，与普通概念间的关系边规则一致

#### Scenario: hub 的邻居边与概念相同

- **WHEN** hub 作为子节点被挂到父节点下
- **THEN** 该边 MUST 为邻居边（`edge_type="neighbor"`），与普通概念被挂到父节点下的规则一致

---

### Requirement: hub 提取时原始边降级而非删除

FanoutReducer 触发裂变时，原始父→子邻居边 MUST NOT 被删除，而是降级为关系边（`edge_type` 从 `"neighbor"` 改为 `"relationship"`，`label` 置空或由系统根据上下文推断）。同时 MUST 新增父→hub 邻居边和 hub→子邻居边。

#### Scenario: root→child 降级为关系边

- **WHEN** FanoutReducer 将 `__seed_root__` 的子节点 C 归入新 hub H
- **THEN** `root→C` 的边 MUST 从 `edge_type="neighbor"` 改为 `edge_type="relationship"`；MUST NOT 删除该边

#### Scenario: 新增 root→hub 邻居边

- **WHEN** FanoutReducer 创建新 hub H
- **THEN** MUST 新增 `(root, H, neighbor, "")` 边

#### Scenario: 新增 hub→child 邻居边

- **WHEN** 子节点 C 被归入 hub H
- **THEN** MUST 新增 `(H, C, neighbor, "")` 边

#### Scenario: 非 root 节点的子节点同样降级

- **WHEN** 非 root 节点 X 的子节点被归入新 hub H
- **THEN** `X→C` 的边 MUST 从 `edge_type="neighbor"` 改为 `edge_type="relationship"`；规则与 root 相同

---

### Requirement: 关系边 label 为粗粒度

关系边的 `label` SHALL 为粗粒度关系描述（如"涉及"、"属于"、"导致"、"包含"），而非完整关系陈述（如"FTX涉及欺诈案"）。同一节点的出边 label SHOULD 做语义统一（避免同义 label 共存），但不同节点之间 MUST NOT 强制统一。

#### Scenario: label 为短词组

- **WHEN** LLM 为一条关系边输出 label
- **THEN** `label` MUST 为 1-4 个字的短词组或短句，MUST NOT 为完整句子

#### Scenario: 同节点出边去重

- **WHEN** 节点 A 有两条出边 label 分别为"涉及"和"关联"且 LLM 判定同义
- **THEN** 系统 SHOULD 将它们统一为同一 label

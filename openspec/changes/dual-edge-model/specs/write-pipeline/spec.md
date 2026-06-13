## MODIFIED Requirements

### Requirement: DecisionList 为纯数据，与图更新严格分离

Stage ④ output MUST be a serializable `DecisionList` containing zero or more decisions (each with an `action` field and action-specific payload). Stage ⑤ SHALL apply the decisions atomically WITHOUT any further LLM call. Decision 的 `edges_to` 字段 MUST 为 `list[dict]`，每项含 `target_id`（str）和 `label`（str），用于创建带 label 的关系边。

#### Scenario: DecisionList 不含 LLM 引用

- **WHEN** 检查 DecisionList 实例
- **THEN** 它 MUST 是纯数据（dataclass/dict 列表）；序列化后 MUST 可被重放（无副作用引用、无活动 LLM 句柄）

#### Scenario: 图更新阶段无 LLM 调用

- **WHEN** 执行 ⑤
- **THEN** 框架 MUST NOT 在 ⑤ 阶段发起任何 LLM 调用；所有改图操作直接对 GraphStore 进行

#### Scenario: create 动作写带 label 的关系边

- **WHEN** create decision 的 `edges_to` 含 `[{"target_id": "X", "label": "涉及"}]`
- **THEN** ⑤ MUST 创建 `(new_node, X, relationship, "涉及")` 边

#### Scenario: merge 动作写带 label 的关系边

- **WHEN** merge decision 的 `edges_to` 含 `[{"target_id": "X", "label": "属于"}]`
- **THEN** ⑤ MUST 创建 `(merged_node, X, relationship, "属于")` 边

#### Scenario: 挂 seed_root 时写邻居边

- **WHEN** 新概念被挂到 `__seed_root__` 下
- **THEN** ⑤ MUST 创建 `(__seed_root__, new_node, neighbor, "")` 边，MUST NOT 创建关系边

---

### Requirement: 概念提取生成自包含描述

阶段 ③ `extract_concepts` 的 prompt MUST 指导 LLM 为每个概念生成简洁但自包含的描述，覆盖概念定义和关键事实。content 长度 SHOULD 控制在合理范围内（不超过 ~200 字符），以避免节点 token 膨胀挤占 BFS 窗口。关系的语义信息由边 label 承载，MUST NOT 全部塞入 content。

#### Scenario: concept content 简洁自包含

- **WHEN** extract_concepts 从文档中提取概念
- **THEN** 每个概念的 `content` MUST 包含定义和关键事实，但 SHOULD NOT 超过 200 字符

#### Scenario: 关系信息由边承载

- **WHEN** 概念 A 和 B 之间的关系需要表达
- **THEN** 系统 MUST 通过边 label（如"涉及"）表达关系，MUST NOT 把关系描述全写入节点 content

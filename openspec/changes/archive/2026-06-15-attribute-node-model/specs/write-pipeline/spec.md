## MODIFIED Requirements

### Requirement: DecisionList 为纯数据，与图更新严格分离

阶段 ④ 输出 MUST 为可序列化的 `DecisionList`；阶段 ⑤ SHALL 原子应用、无 LLM 调用。**`property_graph` 模式**下，Decision 的 `edges_to`（到已有节点）与 `edges_to_names`（到同批新概念）MUST 均为 `list[dict]`（含 `target_id` / `target_name` 与 `label`），用于创建 `kind="fact"` 事实边——**一条事实只存一份**（两端索引），MUST NOT 双向对存；⑤ 第二遍按名解析 `edges_to_names` 时，MUST 同样只写**一条带 label** 的事实边，MUST NOT 再落两条对向单向边。**`attribute_node` 模式**下，⑤ 改为建属性节点 + `kind="assoc"` 无类型边（见 `attribute-node-model`，权威），MUST NOT 建带 label 事实边。两模式的阶段 ⑤ MUST 同为原子应用、无 LLM 调用。

#### Scenario: create 写一条带 label 事实边

- **WHEN** （`property_graph` 模式）create decision 含 `edges_to=[{"target_id": "X", "label": "喜欢"}]`
- **THEN** ⑤ MUST 创建一条 `(new_node, X, kind="fact", label="喜欢")` 边，MUST NOT 同时写反向副本

#### Scenario: merge 写一条带 label 事实边

- **WHEN** （`property_graph` 模式）merge decision 含 `edges_to=[{"target_id": "X", "label": "属于"}]`
- **THEN** ⑤ MUST 创建一条 `(merged_node, X, kind="fact", label="属于")` 边

#### Scenario: 篇内关系（edges_to_names）写单条 label 事实边

- **WHEN** （`property_graph` 模式）同批新概念 X 与 Y 间有关系 `X —label→ Y`（经 `edges_to_names` 按名解析）
- **THEN** ⑤ 第二遍 MUST 创建一条 `(X, Y, kind="fact", label)` 边，MUST NOT 写 `Y→X` 副本

#### Scenario: attribute_node 模式 ⑤ 建属性节点 + assoc 边

- **WHEN** `attribute_node` 模式应用一条关系决策
- **THEN** ⑤ MUST 建 / 复用属性节点并连 `kind="assoc"` 边，MUST NOT 调用 `add_edge(kind="fact")`

#### Scenario: 图更新阶段无 LLM 调用

- **WHEN** 执行 ⑤（两种模式）
- **THEN** 框架 MUST NOT 在 ⑤ 发起任何 LLM 调用

---

### Requirement: 阶段 ④ DecisionList 动作类型简化

**`property_graph` 模式**下，阶段 ④ `judge_relations` 的 DecisionList MUST 限于 3 种动作：`merge`、`create`、`no_op`；`attach_statement` 在该模式 MUST 标记为 deprecated、视为 no-op（保留在动作类型字面量中但不再由管线产生）。merge 决策中 `aliases_to_add` 字段用于让 LLM 贡献额外别名。**`attribute_node` 模式**下，阶段 ④ 走专属 prompt、产出关系具体化决策（建属性节点 + assoc 边），见 `attribute-node-model`（权威）。

#### Scenario: property_graph 模式不产生 attach_statement

- **WHEN** （`property_graph` 模式）阶段 ④ LLM 返回 `action: "attach_statement"`
- **THEN** write_pipeline MUST 将其视为 no-op（不执行任何图操作），并记录 deprecation 警告日志

#### Scenario: DecisionList 不再使用 initial_statements

- **WHEN** （`property_graph` 模式）阶段 ④ LLM 返回 `initial_statements` 字段
- **THEN** write_pipeline MUST 忽略该字段，不写入 `extensions["statements"]`

#### Scenario: merge 动作含 aliases_to_add

- **WHEN** （`property_graph` 模式）④ 决定一个概念已存在为节点 X
- **THEN** DecisionList 中 MUST 含一项 `{action: "merge", concept: c, target_id: X_id, aliases_to_add: [...]}`
- **AND** `aliases_to_add` MUST 包含 LLM 识别的同义词、缩写、变体写法

#### Scenario: create 动作

- **WHEN** （`property_graph` 模式）④ 决定一个概念是新概念
- **THEN** DecisionList 中 MUST 含一项 `{action: "create", concept: c, edges_to: [anchor_ids]}`

#### Scenario: no_op 动作

- **WHEN** ④ 决定某概念不值得入图（如太宽泛或与现有图无关）
- **THEN** DecisionList 中 MUST 含一项 `{action: "no_op", concept: c, reason: "..."}`；⑤ 跳过该项

#### Scenario: attribute_node 模式产关系具体化决策

- **WHEN** `attribute_node` 模式执行阶段 ④
- **THEN** DecisionList MUST 表达"建 / 并属性节点 + 连无类型边"的意图，MUST NOT 含关系 label

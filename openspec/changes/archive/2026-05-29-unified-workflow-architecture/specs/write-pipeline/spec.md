## ADDED Requirements

### Requirement: 写流程为 6 段固定管线

The system SHALL implement ingest as a 6-stage pipeline in this fixed order: ① 前置插件链 → ② 关联节点定位 → ③ 概念提取 → ④ 关系判定 → ⑤ 图更新 → ⑥ 压缩判定插件链.

#### Scenario: 6 段顺序固定

- **WHEN** 调用 `WritePipeline.ingest(text, **metadata)`
- **THEN** 框架 MUST 按 ①→②→③→④→⑤→⑥ 顺序执行；任何插件不得调整段的顺序

#### Scenario: 写流程不含独立仲裁段

- **WHEN** 审查写流程的段定义
- **THEN** 写流程 MUST NOT 含与读流程 ④ 对称的"仲裁段"；判定/选择动作 MUST 由 ④ 关系判定步完成（决策清单本身即仲裁产物）

#### Scenario: 写流程不含内部 Loop

- **WHEN** 一次 `ingest()` 调用
- **THEN** 框架 MUST 按线性 6 段执行；不在框架内做"对超长 text 自动分批 Loop"；分批由调用方决定

---

### Requirement: 关联节点定位通过复用读流程实现

Stage ② SHALL invoke the query pipeline internally with `processed_text` (output of stage ①) as the query string. The returned `List[Node]` becomes `WriteContext.related` and feeds stages ③④.

#### Scenario: 写入复用读流程

- **WHEN** 执行 ②
- **THEN** 框架 MUST 调用 `QueryEngine.query(processed_text)` 或等价内部方法；返回值 MUST 作为后续阶段的 `related` 字段

#### Scenario: 关联定位失败不阻塞写入

- **WHEN** ② 返回空 `related`（图中暂无相关节点，如全新疆域）
- **THEN** 框架 MUST 继续执行 ③；③ 在没有 `related` 参考时 LLM 仍可基于纯 `text` 抽概念

#### Scenario: 关联定位的 LLM 调用计入预算

- **WHEN** ② 内部调用的读流程触发了 ③ 语义遍历 Loop
- **THEN** 框架 MUST 把这些 LLM 调用计入本次 ingest 的总调用计数（用于监控/限流）

---

### Requirement: 概念提取与关系判定分两次 LLM 调用

Stages ③ and ④ SHALL be implemented as TWO separate LLM calls, not merged into one. Stage ③ produces `List[ConceptDraft]`; stage ④ takes `(ConceptDrafts, related)` and produces `DecisionList`.

#### Scenario: 概念提取单一职责

- **WHEN** 执行 ③
- **THEN** LLM 调用的 `purpose` MUST 是 `extract_concepts`；输入 MUST 含 `processed_text` 和 `related`；输出 MUST 仅含 ConceptDraft 列表，不含关系决策

#### Scenario: 关系判定单一职责

- **WHEN** 执行 ④
- **THEN** LLM 调用的 `purpose` MUST 是 `judge_relations`；输入 MUST 含 ConceptDrafts 和 `related`；输出 MUST 仅含 DecisionList，不含图操作的实际执行

#### Scenario: 两步合并的优化不在 Phase 1

- **WHEN** 实现 ③④
- **THEN** Phase 1 MUST 实现为两次独立 LLM 调用；"合并优化"作为未来优化空间但不在 Phase 1 范围

---

### Requirement: DecisionList 为纯数据，与图更新严格分离

Stage ④ output MUST be a serializable `DecisionList` containing zero or more decisions (each with an `action` field and action-specific payload). Stage ⑤ SHALL apply the decisions atomically WITHOUT any further LLM call.

#### Scenario: DecisionList 不含 LLM 引用

- **WHEN** 检查 DecisionList 实例
- **THEN** 它 MUST 是纯数据（dataclass/dict 列表）；序列化后 MUST 可被重放（无副作用引用、无活动 LLM 句柄）

#### Scenario: 图更新阶段无 LLM 调用

- **WHEN** 执行 ⑤
- **THEN** 框架 MUST NOT 在 ⑤ 阶段发起任何 LLM 调用；所有改图操作直接对 GraphStore 进行

#### Scenario: 决策清单可被插件干预

- **WHEN** 有插件在 ④ 之后、⑤ 之前需要审计或过滤决策
- **THEN** 框架 MUST 在 DecisionList 上提供干预点（具体接口形态由 Phase 1 决定，但 spec 要求该干预可能）

---

### Requirement: DecisionList 至少支持四种 action

The `DecisionList` schema SHALL support at least these action types: `merge` (合并概念到已有节点), `create` (新建节点并连边), `attach_statement` (向属性节点挂说法), `no_op` (LLM 决定该概念不入图).

#### Scenario: merge 动作

- **WHEN** ④ 决定一个概念已存在为节点 X
- **THEN** DecisionList 中 MUST 含一项 `{action: "merge", concept: c, target_id: X_id, aliases_to_add: [...]}`

#### Scenario: create 动作

- **WHEN** ④ 决定一个概念是新概念
- **THEN** DecisionList 中 MUST 含一项 `{action: "create", concept: c, edges_to: [anchor_ids], initial_statements: [...]}`

#### Scenario: attach_statement 动作

- **WHEN** ④ 决定为已有属性节点追加一条说法
- **THEN** DecisionList 中 MUST 含一项 `{action: "attach_statement", target_attr_node_id: D_id, statement: "..."}`

#### Scenario: no_op 动作

- **WHEN** ④ 决定某概念不值得入图（如太宽泛或与现有图无关）
- **THEN** DecisionList 中 MUST 含一项 `{action: "no_op", concept: c, reason: "..."}`；⑤ 跳过该项

---

### Requirement: 压缩判定为插件链且条件触发

Stage ⑥ SHALL accept 0..N `CompactionPluginInterface` instances. Each plugin MUST expose `should_run(changed_nodes, graph) -> bool`; only plugins whose `should_run` returns True will execute `run()`.

#### Scenario: 没有配置压缩插件时 ⑥ 直接跳过

- **WHEN** 配置中不含任何 CompactionPlugin
- **THEN** 框架 MUST 跳过 ⑥；ingest 直接结束

#### Scenario: 压缩插件按条件触发

- **WHEN** ⑥ 含两个插件 P1 和 P2，且仅 P1.should_run 返回 True
- **THEN** 框架 MUST 执行 P1.run，跳过 P2.run

#### Scenario: 压缩插件可发起 LLM 调用

- **WHEN** FanoutReducerPlugin.run 需要让 LLM 选择枢纽
- **THEN** 框架 MUST 允许插件通过传入的 `llm_caller` 句柄发起 LLM 调用；这些调用计入本次 ingest

#### Scenario: 压缩链串联接收上游产物

- **WHEN** ⑥ 含 P1（降扇出）和 P2（重生成摘要）
- **THEN** P2.run 接收的 `changed_nodes` MUST 反映 P1.run 之后的图状态（含 P1 新引入的枢纽节点）

---

### Requirement: WriteContext 含七个状态字段

The system SHALL provide a `WriteContext` data class threaded through the entire ingest call, containing these 7 lifecycle fields: `system_prompt`, `user_input`, `processed`, `related`, `concepts`, `decisions`, `changed`. Free `metadata` dict allowed.

#### Scenario: 字段与段对应

- **WHEN** 检查 WriteContext 字段
- **THEN** `processed` MUST 由 ① 写入；`related` MUST 由 ② 写入；`concepts` MUST 由 ③ 写入；`decisions` MUST 由 ④ 写入；`changed` MUST 由 ⑤ 写入；`system_prompt` 与 `user_input` 整次调用不变

#### Scenario: 后续段可读取前序段产物

- **WHEN** 阶段 N 的代码访问 ctx 字段
- **THEN** 它 MUST 能读取所有 0..N-1 段写入的字段；MUST NOT 依赖 N+1 及之后的字段

---

### Requirement: 写流程无独立仲裁位

The write pipeline SHALL NOT have a stage analogous to query stage ④ arbitration. Decision-making (which concept maps to which existing node, which gets created) MUST happen inside stage ④ 关系判定 as part of the LLM judgment output.

#### Scenario: 设计文档明确说明

- **WHEN** 审查 write-pipeline spec 和 design.md
- **THEN** MUST 明确"写流程 ④ 即是写入的仲裁动作"；MUST 不引入独立 ArbitrationPlugin 在写流程中

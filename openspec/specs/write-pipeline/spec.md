# write-pipeline Specification

## Purpose
定义写流程为 7 段固定管线（前置插件→关联节点定位→概念提取→关系判定→图更新→压缩判定→自动落盘），线性执行无内部 Loop。
## Requirements
### Requirement: 写流程为 7 段固定管线

The system SHALL implement ingest as a 7-stage pipeline in this fixed order: ① 前置插件链 → ② 关联节点定位 → ③ 概念提取 → ④ 关系判定 → ⑤ 图更新 → ⑥ 压缩判定插件链 → ⑦ 自动落盘.

#### Scenario: 7 段顺序固定

- **WHEN** 调用 `WritePipeline.ingest(text, **metadata)`
- **THEN** 框架 MUST 按 ①→②→③→④→⑤→⑥→⑦ 顺序执行；任何插件不得调整段的顺序

#### Scenario: 写流程不含独立仲裁段

- **WHEN** 审查写流程的段定义
- **THEN** 写流程 MUST NOT 含与读流程 ④ 对称的"仲裁段"；判定/选择动作 MUST 由 ④ 关系判定步完成（决策清单本身即仲裁产物）

#### Scenario: 写流程不含内部 Loop

- **WHEN** 一次 `ingest()` 调用
- **THEN** 框架 MUST 按线性 7 段执行；不在框架内做"对超长 text 自动分批 Loop"；分批由调用方决定

---

### Requirement: 阶段 ① 使用独立的 PreprocessPlugin 类型

The system SHALL modify stage ① (前置插件链) to use `PluginType.WRITE_PREPROCESS` for locating plugins. WritePreprocessPluginInterface only processes text; it MUST NOT control pipeline flow (e.g. skip). Idempotency checks SHALL be the caller's responsibility (e.g. `update_document()` checks `is_ingested()` before calling `ingest()`).

#### Scenario: 写入前置插件类型独立

- **WHEN** 写入管线执行阶段 ①
- **THEN** 框架 MUST 通过 `plugin_manager.get_all(PluginType.WRITE_PREPROCESS)` 获取前置插件链

#### Scenario: 写入前置插件处理文本

- **WHEN** 写入前置插件链执行
- **THEN** 每个插件的输入和输出 MUST 是 `str` 类型

#### Scenario: 幂等检查由调用方负责

- **WHEN** 调用方需要避免重复摄入
- **THEN** 调用方 MUST 在调用 `ingest()` 前使用 `IdempotencyCheckPlugin.is_ingested()` 检查；`WritePreprocessPluginInterface` MUST NOT 通过 `ctx.skip` 控制管线流程

---

### Requirement: 关联节点定位通过轻量查询模式实现

Stage ② SHALL invoke `QueryEngine.query_nodes(processed_text)` (lightweight mode) instead of `QueryEngine.query(processed_text)`. The returned `List[Node]` becomes `WriteContext.related` and feeds stages ③④. The framework MUST NOT contain `isinstance(related, list) else []` silent degradation logic.

#### Scenario: 写入使用轻量查询模式

- **WHEN** 执行 ②
- **THEN** 框架 MUST 调用 `QueryEngine.query_nodes(processed_text)` 或等价内部方法；MUST NOT 调用 `QueryEngine.query(processed_text)`

#### Scenario: 关联定位失败不阻塞写入

- **WHEN** ② 返回空 `related`（图中暂无相关节点，如全新疆域）
- **THEN** 框架 MUST 继续执行 ③；③ 在没有 `related` 参考时 LLM 仍可基于纯 `text` 抽概念

#### Scenario: 关联定位的 LLM 调用计入预算

- **WHEN** ② 内部调用的轻量查询触发了遍历
- **THEN** 框架 MUST 把这些 LLM 调用计入本次 ingest 的总调用计数（用于监控/限流）

#### Scenario: 返回值直接赋给 related

- **WHEN** `query_nodes` 返回结果 R
- **THEN** `ctx.related` MUST 直接等于 R；MUST NOT 包含 `isinstance(R, list) else []` 转换逻辑

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

### Requirement: 阶段 ④ DecisionList 动作类型简化

阶段 ④ `judge_relations` 的 DecisionList 从 4 种动作简化为 3 种：`merge`、`create`、`no_op`。`attach_statement` 标记为 deprecated，保留在动作类型字面量中但不再由管线产生。merge 决策中 `aliases_to_add` 字段用于让 LLM 贡献额外别名。

#### Scenario: DecisionList 不再产生 attach_statement

- **WHEN** 阶段 ④ LLM 返回 `action: "attach_statement"`
- **THEN** write_pipeline MUST 将其视为 no-op（不执行任何图操作），并记录 deprecation 警告日志

#### Scenario: DecisionList 不再使用 initial_statements

- **WHEN** 阶段 ④ LLM 返回 `initial_statements` 字段
- **THEN** write_pipeline MUST 忽略该字段，不写入 `extensions["statements"]`

#### Scenario: merge 动作含 aliases_to_add

- **WHEN** ④ 决定一个概念已存在为节点 X
- **THEN** DecisionList 中 MUST 含一项 `{action: "merge", concept: c, target_id: X_id, aliases_to_add: [...]}`
- **AND** `aliases_to_add` MUST 包含 LLM 识别的同义词、缩写、变体写法

#### Scenario: create 动作

- **WHEN** ④ 决定一个概念是新概念
- **THEN** DecisionList 中 MUST 含一项 `{action: "create", concept: c, edges_to: [anchor_ids]}`

#### Scenario: no_op 动作

- **WHEN** ④ 决定某概念不值得入图（如太宽泛或与现有图无关）
- **THEN** DecisionList 中 MUST 含一项 `{action: "no_op", concept: c, reason: "..."}`；⑤ 跳过该项

---

### Requirement: merge 时 concept content 追加到目标节点

`_dispatch_merge` 在合并概念时，MUST 将 `decision.concept.content` 追加到目标节点的 `content` 字段（而非写入 statements extensions）。追加后若 content 超过阈值，MUST 触发 LLM 压缩。

#### Scenario: merge 追加 content

- **WHEN** merge decision 的 `concept.content` 非空
- **AND** `concept.content` 不是目标节点 `content` 的子串
- **THEN** write_pipeline MUST 将 `concept.content` 以换行符追加到目标节点的 `content`

#### Scenario: merge 跳过重复 content

- **WHEN** merge decision 的 `concept.content` 已经是目标节点 `content` 的子串
- **THEN** write_pipeline MUST NOT 重复追加

#### Scenario: merge 后 content 超阈值触发压缩

- **WHEN** merge 追加 content 后目标节点 `content` 长度超过 `merge_content_threshold`（默认 500）
- **THEN** write_pipeline MUST 调用 `gen_summary` purpose 对 content 进行压缩重写
- **AND** 压缩后 content 长度 MUST <= threshold

#### Scenario: merge 压缩失败降级

- **WHEN** merge 后 content 超阈值但压缩 LLM 调用失败
- **THEN** write_pipeline MUST 保留追加后的原始 content 并记录 warning 日志

---

### Requirement: create 时不再写入 statements

`_dispatch_create` 在创建新节点时，MUST NOT 将 `initial_statements` 写入 `node.extensions["statements"]`。节点的 `content` 已由 `extract_concepts` prompt 保证包含充分信息。

#### Scenario: create 不写入 statements

- **WHEN** create decision 带有 `initial_statements` 字段
- **THEN** write_pipeline MUST 忽略该字段，新节点无 statements extension

---

### Requirement: 概念提取生成精简自包含描述

阶段 ③ `extract_concepts` 的 prompt MUST 指导 LLM 生成**精简**的自包含描述：仅含定义 + 短叶子属性，控制在 **lean 基线**（**~24 token**；英文约 100 字符，中文按 token 计）。关系语义 MUST NOT 写入 content（由事实边承载）。

#### Scenario: content 精简且不含关系叙述

- **WHEN** `extract_concepts` 提取概念
- **THEN** `content` MUST 仅含定义 + 短属性，SHOULD NOT 超过 lean 基线，MUST NOT 含成句关系叙述

---

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

---

### Requirement: 压缩判定为插件链且条件触发（含不变量守门）

Stage ⑥ SHALL accept 0..N `CompactionPluginInterface` instances. Each plugin MUST expose `should_run(changed_nodes, store) -> bool`; only plugins whose `should_run` returns True will execute `run()`. `should_run` MUST check for invariant violations (root + changed + affected nodes exceeding budget) as part of its condition.

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

### Requirement: WriteContext 含八个状态字段（不含 skip）

The system SHALL provide a `WriteContext` data class threaded through the entire ingest call, containing these 8 lifecycle fields: `system_prompt`, `user_input`, `processed`, `related`, `concepts`, `decisions`, `changed`, `persisted`. Free `metadata` dict allowed. WriteContext MUST NOT contain a `skip` field; pipeline flow control is the caller's responsibility.

#### Scenario: 字段与段对应

- **WHEN** 检查 WriteContext 字段
- **THEN** `processed` MUST 由 ① 写入；`related` MUST 由 ② 写入；`concepts` MUST 由 ③ 写入；`decisions` MUST 由 ④ 写入；`changed` MUST 由 ⑤ 写入；`persisted` MUST 由 ⑦ 写入；`system_prompt` 与 `user_input` 整次调用不变

#### Scenario: 后续段可读取前序段产物

- **WHEN** 阶段 N 的代码访问 ctx 字段
- **THEN** 它 MUST 能读取所有 0..N-1 段写入的字段；MUST NOT 依赖 N+1 及之后的字段

#### Scenario: persisted 记录落盘结果

- **WHEN** 阶段 ⑦ 完成
- **THEN** ctx.persisted MUST 是一个布尔值（True 表示成功落盘，False 表示跳过或失败）

---

### Requirement: 写流程无独立仲裁位

The write pipeline SHALL NOT have a stage analogous to query stage ④ arbitration. Decision-making (which concept maps to which existing node, which gets created) MUST happen inside stage ④ 关系判定 as part of the LLM judgment output.

#### Scenario: 设计文档明确说明

- **WHEN** 审查 write-pipeline spec 和 design.md
- **THEN** MUST 明确"写流程 ④ 即是写入的仲裁动作"；MUST 不引入独立 ArbitrationPlugin 在写流程中

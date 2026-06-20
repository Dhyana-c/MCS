# write-pipeline Specification

## Purpose
定义写流程为 7 段固定管线（前置插件→关联节点定位→概念提取→关系判定→图更新→压缩判定→自动落盘），线性执行无内部 Loop。
## Requirements
### Requirement: 写流程为 7 段固定管线

The system SHALL implement ingest with a deterministic 规则入库前置段 ⓪ followed by the 7-stage LLM core pipeline in this fixed order: ⓪ 规则入库（建事件 + 可选 source 节点，不经 LLM）→ ① 前置插件链 → ② 关联节点定位 → ③ 概念提取 → ④ 关系判定 → ⑤ 图更新（含事件 / source → 概念 / 事实 背书连边）→ ⑥ 压缩判定插件链 → ⑦ 自动落盘. ingest 入参 SHALL 接受 `str | IngestInput`；`str` MUST 被归一化为 `IngestInput(content=text)`（now 时间戳、无 source），既有 `str` 调用行为 MUST 保持不变（除新增的一条记录事件外）。

#### Scenario: 规则入库先于 LLM 核心管线

- **WHEN** 调用 `WritePipeline.ingest(data, **metadata)`
- **THEN** ⓪ MUST 先建事件（及可选 source）节点、不经 LLM，再执行 ①–⑦
- **AND** ⓪ 建的事件 / source 节点 id MUST 可用于 ⑤ 的背书连边

#### Scenario: 7 段核心顺序固定

- **WHEN** ⓪ 完成之后
- **THEN** 框架 MUST 按 ①→②→③→④→⑤→⑥→⑦ 顺序执行；任何插件不得调整段的顺序

#### Scenario: str 向后兼容

- **WHEN** 以 `str` 调用 `ingest`
- **THEN** MUST 归一化为 `IngestInput(content=text)`（无 source、now 时间戳）
- **AND** 概念 / 事实抽取与连边行为 MUST 与既有 `str` 路径逐字等价

#### Scenario: 写流程不含独立仲裁段

- **WHEN** 审查写流程的段定义
- **THEN** 写流程 MUST NOT 含与读流程 ④ 对称的"仲裁段"；判定/选择动作 MUST 由 ④ 关系判定步完成（决策清单本身即仲裁产物）

#### Scenario: 写流程不含内部 Loop

- **WHEN** 一次 `ingest()` 调用
- **THEN** 框架 MUST 按线性段执行；不在框架内做"对超长 text 自动分批 Loop"；分批由调用方决定

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

阶段 ④ 输出 MUST 为可序列化的 `DecisionList`；阶段 ⑤ SHALL 原子应用、**无 LLM 调用**。关系 MUST 具体化为**命题（事实）节点**（`node_class=事实`，谓词落其 `content`）+ `关联` 边连其端点；MUST NOT 建带 `label` 的事实边、MUST NOT 按 `relation_model` 分模式。互斥 MUST 表示为两个事实节点间的 `互斥` 边。

#### Scenario: ⑤ 关系建命题节点 + 关联边

- **WHEN** 应用一条关系决策（X 与 Y 有关系"喜欢"）
- **THEN** ⑤ MUST 建 / 复用命题节点（content 含"喜欢"），并连 `X —关联— 命题`、`命题 —关联— Y`
- **AND** MUST NOT 调用 `add_edge(kind="fact")`、MUST NOT 产生带 label 的边

#### Scenario: 图更新阶段无 LLM 调用

- **WHEN** 执行 ⑤
- **THEN** 框架 MUST NOT 在 ⑤ 发起任何 LLM 调用

---

### Requirement: 阶段 ④ DecisionList 动作类型简化

阶段 ④ `judge_relations` 的**概念级**动作 MUST 限于 `merge` / `create` / `no_op`（`attach_statement` 移除）。关系判定 MUST 产出"建 / 复用命题节点 + 连 `关联` 边（必要时连 `互斥`）"的意图，MUST NOT 产出关系 `label`、MUST NOT 按 `relation_model` 分模式。`merge` 决策的 `aliases_to_add` 字段用于让 LLM 贡献别名。

#### Scenario: 概念动作三选一

- **WHEN** ④ 判定一个概念
- **THEN** DecisionList 对该概念 MUST 取 `merge`（已存在节点 X，含 `aliases_to_add`）/ `create`（新概念）/ `no_op`（不入图）之一

#### Scenario: 关系产命题节点意图、无 label

- **WHEN** ④ 判定两节点有关系
- **THEN** 决策 MUST 表达"建 / 并命题节点 + 连关联边"的意图，MUST NOT 含关系 `label`

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

阶段 ③ `extract_concepts` 的 prompt MUST 指导 LLM 生成**精简**的自包含**概念**描述：仅含定义 + 短叶子属性，控制在 **lean 基线**（**~24 token**）。关系语义 MUST NOT 写入概念 `content`——关系由**命题（事实）节点**承载（谓词落其 content）。

#### Scenario: 概念 content 精简且不含关系叙述

- **WHEN** `extract_concepts` 提取一个概念
- **THEN** 其 `content` MUST 仅含定义 + 短属性，MUST NOT 含成句关系叙述（关系归命题节点）

---

### Requirement: root 关联可选——只挂孤儿

挂接 MUST 仅在新节点**与任何既有节点零关联**（无任何 `关联` 边）时，才创建 `__seed_root__ → node` 的 `关联` 边（孤儿之家）。有 ≥1 条关联的节点 MUST NOT 挂 root（经关联可达）。`__seed_root__` 是普通组织中心（hub 标记），其出边 MUST 为 `关联`。

#### Scenario: 有关联不挂 root

- **WHEN** 新节点已与至少一个既有节点建立 `关联` 边
- **THEN** 系统 MUST NOT 为它创建 `root → node` 边

#### Scenario: 零关联挂 root

- **WHEN** 新节点与任何既有节点都无关联
- **THEN** 系统 MUST 创建 `__seed_root__ → node` 的 `关联` 边

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

### Requirement: ingest 输入为结构体，事件 / source 字段不经 LLM

The system SHALL accept ingest input as an `IngestInput` data class with fields `content`、`timestamp`（可选，ISO 8601）、`source`（可选，`SourceData`）、`event_name`（可选）、`metadata`。`content` SHALL 是唯一进入 LLM 概念 / 事实抽取的字段；`timestamp` / `source` / `event_name` MUST 仅由规则消费、MUST NOT 经 LLM。

#### Scenario: 结构体字段分工

- **WHEN** 调用 `ingest(IngestInput(content=..., timestamp=..., source=...))`
- **THEN** 只有 `content` MUST 进入 LLM 抽取
- **AND** 事件 `timestamp`、source 切分 MUST 由规则处理、不经 LLM

### Requirement: 每次 ingest 整个输入记为一个事件

每次 `ingest` 调用 SHALL 把整个输入记为**一个事件节点**（`node_class=事件`，`timestamp` = 输入 `timestamp` 或缺省 now），表示"记录此输入"这一**行为**、落用户时间轴。content 内被转述的过去事件 MUST 仍按 `unified-graph-schema`「事件不经 LLM 抽取」规则抽成**带时间属性的事实**，MUST NOT 盖成时间轴事件。

#### Scenario: 一次 ingest 恰一个记录事件

- **WHEN** 调用 `ingest`（无论 content 是否抽出概念 / 事实）
- **THEN** MUST 恰好创建一个事件节点，`timestamp` 为输入 timestamp（缺省 now）
- **AND** 即便 content 抽取为零概念 / 事实，该事件节点 MUST 仍入库并随 ⑦ 落盘

#### Scenario: 转述过去事件不成时间轴事件

- **WHEN** content 含"三年前发生 X"这类转述
- **THEN** X MUST 被抽成带时间属性的**事实**（核心图）
- **AND** MUST NOT 成为第二个时间轴事件节点

### Requirement: 事件 / source 背书本次抽出的概念 / 事实

图更新（⑤）后，⓪ 建的事件与 source 节点 SHALL 对**本次新建 / 命中的概念 / 事实**连 `事件 → 概念 / 事实`、`source → 概念 / 事实` 的 `关联` 背书边（方向固定，事件 / source 为源端）。载重规则 MUST 不变：核心节点（`node_class ∈ {概念, 事实}`）的 `get_relations` MUST 仍过滤对端为事件的边。

#### Scenario: 背书连边且不破载重

- **WHEN** 一次 ingest 抽出概念 C / 事实 F，⓪ 建了事件 E（及 source S）
- **THEN** MUST 存在 `E → C` / `E → F`（及 `S → C` / `S → F`）的 `关联` 边
- **AND** `get_relations(C)`（核心节点）MUST NOT 含 `E → C` 事件边
- **AND** `get_related_events(C)` MUST 可达 E

#### Scenario: source 规则切分

- **WHEN** `IngestInput.source` 提供多个 chunks
- **THEN** 每个 chunk MUST 建一个 source 节点（保真、不经 LLM）
- **AND** 各 source 节点 MUST 对本次抽出的概念 / 事实连关联背书边

### Requirement: WriteContext 携带规则入库产物

`WriteContext` SHALL 额外携带 ⓪ 规则入库的产物：本次事件节点与 source 节点列表，供 ⑤ 背书连边与 ⑦ 落盘引用。此为对既有八个生命周期字段的补充，MUST NOT 移除既有字段。

#### Scenario: ctx 暴露事件 / source 产物

- **WHEN** ⓪ 规则入库完成
- **THEN** `ctx` MUST 暴露本次事件节点与 source 节点列表
- **AND** ⑤ MUST 能据此连背书边、⑦ MUST 能据此落盘


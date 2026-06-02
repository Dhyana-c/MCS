## ADDED Requirements

### Requirement: 写入管线在图更新后自动持久化变更

WritePipeline SHALL 在阶段 ⑥ 压缩判定完成后执行阶段 ⑦ 自动落盘：将 `ctx.changed` 中的节点及关联边增量持久化到 StorageInterface。

#### Scenario: 每次 ingest 触发落盘

- **WHEN** WritePipeline.ingest() 完成阶段 ⑤ 图更新并产生 `ctx.changed`（非空）
- **THEN** 框架 MUST 调用 StorageInterface.save_node() 持久化每个 changed 节点；MUST 调用 StorageInterface.save_edge() 持久化新增边

#### Scenario: changed 为空时跳过落盘

- **WHEN** 阶段 ⑤ 产生空的 `ctx.changed`（如所有 decision 为 no_op）
- **THEN** 框架 MUST 不发起任何 save_node / save_edge 调用

#### Scenario: 边落盘覆盖新增边

- **WHEN** 阶段 ⑤ 的 create 动作创建了节点 N 并通过 edges_to 连接到锚点 A
- **THEN** 阶段 ⑦ MUST 持久化边 (N, A)；若 A 也在 changed 中，边 MUST 只落盘一次

#### Scenario: 落盘失败不阻塞返回

- **WHEN** StorageInterface.save_node() 抛出异常（如磁盘满、连接断开）
- **THEN** 框架 MUST 捕获异常并记录警告；ingest MUST 正常返回 WriteContext（不抛异常到调用方）

---

### Requirement: MCSConfig 支持 auto_persist 配置开关

MCSConfig SHALL 提供 `auto_persist: bool` 字段，默认值为 True。WritePipeline 在阶段 ⑦ 检查该开关决定是否执行落盘。

#### Scenario: auto_persist=True 时落盘

- **WHEN** config.auto_persist == True 且 StorageInterface 已注册
- **THEN** WritePipeline MUST 执行阶段 ⑦ 落盘

#### Scenario: auto_persist=False 时跳过落盘

- **WHEN** config.auto_persist == False
- **THEN** WritePipeline MUST 跳过阶段 ⑦，直接返回 WriteContext

#### Scenario: 无 StorageInterface 时跳过落盘

- **WHEN** config.auto_persist == True 但 PluginManager 中未注册 StorageInterface
- **THEN** WritePipeline MUST 跳过阶段 ⑦，记录警告

---

### Requirement: MCS 启动时自动加载已有数据

MCS.initialize() SHALL 在所有插件初始化完成后检查 StorageInterface。若存在且 GraphStore 中无节点，则调用 `storage.load()` 填充 graph。

#### Scenario: 图为空时自动加载

- **WHEN** MCS.initialize() 完成插件初始化，graph.get_all_nodes() 返回空列表，且 StorageInterface 已注册
- **THEN** 框架 MUST 调用 storage.load() 并将返回的 GraphStore 内容合并到 self.graph

#### Scenario: 图已有数据时不加载

- **WHEN** MCS.initialize() 时 graph 已有节点（如手动 pre-populated）
- **THEN** 框架 MUST 不调用 storage.load()，保留现有内存数据

#### Scenario: 加载失败时继续初始化

- **WHEN** storage.load() 抛出异常（如文件不存在、损坏）
- **THEN** 框架 MUST 捕获异常并记录警告；initialize MUST 正常完成（不抛异常）

---

### Requirement: 写流程增加第七阶段定义

WritePipeline spec SHALL 扩展为 7 阶段管线：① 前置插件链 → ② 关联节点定位 → ③ 概念提取 → ④ 关系判定 → ⑤ 图更新 → ⑥ 压缩判定插件链 → ⑦ 自动落盘。

#### Scenario: 7 段顺序固定

- **WHEN** 调用 WritePipeline.ingest(text)
- **THEN** 框架 MUST 按 ①→②→③→④→⑤→⑥→⑦ 顺序执行；任何插件不得调整段的顺序

#### Scenario: ⑦ 在 ⑥ 之后执行

- **WHEN** 阶段 ⑥ 压缩插件链执行完成
- **THEN** 框架 MUST 执行阶段 ⑦ 自动落盘；⑦ MUST 是最后一个阶段

---

### Requirement: 持久化必须保真 round-trip

Persisted node extension data SHALL survive a save→load round-trip in a directly usable form (typed/dict), not as stringified reprs.

#### Scenario: 扩展数据 round-trip 后可用

- **WHEN** 一个带 `source_tracking`（含 `Source` 记录）的节点被 `save_node` 落盘，随后由 `load()` 读回
- **THEN** 读回节点的 `extensions["source_tracking"]["sources"]` MUST 是结构化记录（dict/Source），消费方 MUST 能直接取到 `doc_id` 等字段（MUST NOT 是 `"Source(...)"` 字符串）

#### Scenario: 向后兼容历史字符串格式

- **WHEN** `load()` 遇到历史 db 中以字符串化 `Source(...)` 形式存储的来源
- **THEN** 框架 MUST 容忍并正确还原其字段（如解析出 `doc_id`），使既有 db 无需重建即可复用

---

### Requirement: 持久化变更必须提交且可被独立读取

Each ingest's persisted nodes/edges SHALL be committed promptly, so an independent reader sees them and no in-flight data is lost on shutdown.

#### Scenario: 每次 ingest 后提交

- **WHEN** 一次 ingest 的阶段 ⑦ 落盘了 `ctx.changed` 的节点与边
- **THEN** 框架 MUST 在该次落盘后提交（commit），使另一个独立连接能读到这些节点/边

#### Scenario: shutdown 不丢最后一块

- **WHEN** 连续多次 ingest 后正常 shutdown
- **THEN** 所有已成功 ingest 的块对应的节点 MUST 已提交持久化（MUST NOT 丢失最后一次 ingest 的变更）

---

### Requirement: 续跑无空洞（幂等标记与落盘一致）

The idempotency marker for a chunk SHALL be written only after that chunk's nodes are successfully persisted, so resume never skips a chunk whose nodes were not stored.

#### Scenario: 成功后才标记已摄入

- **WHEN** 一个 `(doc_id, chunk_id)` 块走完写入管线并成功落盘
- **THEN** 框架 MUST 此时才把该块记入 `document_chunks`（去重检查仍可在前置阶段读取该表）

#### Scenario: 出错的块续跑会重试

- **WHEN** 某块在落盘前因异常中断（未成功持久化其节点）
- **THEN** 该块 MUST NOT 被标记为已摄入；续跑时框架 MUST 重新摄入该块（不留图空洞）

---

## MODIFIED Requirements

### Requirement: 写流程为 6 段固定管线

The system SHALL implement ingest as a **7-stage** pipeline in this fixed order: ① 前置插件链 → ② 关联节点定位 → ③ 概念提取 → ④ 关系判定 → ⑤ 图更新 → ⑥ 压缩判定插件链 → ⑦ 自动落盘.

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

### Requirement: WriteContext 含七个状态字段

The system SHALL provide a `WriteContext` data class threaded through the entire ingest call, containing these **8** lifecycle fields: `system_prompt`, `user_input`, `processed`, `related`, `concepts`, `decisions`, `changed`, `persisted`. Free `metadata` dict allowed.

#### Scenario: 字段与段对应

- **WHEN** 检查 WriteContext 字段
- **THEN** `processed` MUST 由 ① 写入；`related` MUST 由 ② 写入；`concepts` MUST 由 ③ 写入；`decisions` MUST 由 ④ 写入；`changed` MUST 由 ⑤ 写入；`persisted` MUST 由 ⑦ 写入；`system_prompt` 与 `user_input` 整次调用不变

#### Scenario: 后续段可读取前序段产物

- **WHEN** 阶段 N 的代码访问 ctx 字段
- **THEN** 它 MUST 能读取所有 0..N-1 段写入的字段；MUST NOT 依赖 N+1 及之后的字段

#### Scenario: persisted 记录落盘结果

- **WHEN** 阶段 ⑦ 完成
- **THEN** ctx.persisted MUST 是一个布尔值（True 表示成功落盘，False 表示跳过或失败）
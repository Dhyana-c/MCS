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

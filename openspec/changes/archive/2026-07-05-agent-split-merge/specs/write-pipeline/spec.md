## ADDED Requirements

### Requirement: WritePipeline 暴露 public 守门入口 run_compaction

`WritePipeline` SHALL 暴露 public 方法 `run_compaction(changed_nodes: list[Node]) -> None`，等价于内部阶段⑥ `_run_compaction(changed_nodes)`——对 `changed_nodes` 跑 `CompactionPlugin` 链、并对层级视图超 `token_budget.T` 的节点强制裂变兜底（保核心不变量）。`MCS` SHALL 暴露同名 public 方法 `run_compaction(changed_nodes)`，转发 `self.write_pipeline.run_compaction(changed_nodes)`。两方法供**外部图手术**（如 agent 层 `split` / `merge` 工具）改图后过守门，**不重跑阶段 ①–⑤ / ⑦**、不触碰 `WriteContext`。既有 `_run_compaction` 行为 MUST NOT 改变（ingest 阶段⑥仍调它）。

#### Scenario: public 守门入口存在且转发

- **WHEN** 调用 `MCS.run_compaction(changed_nodes)` 或 `WritePipeline.run_compaction(changed_nodes)`
- **THEN** MUST 等价于对 `changed_nodes` 执行阶段⑥守门（`CompactionPlugin` 链 + 超 T 兜底裂变）
- **AND** MUST NOT 重跑 ingest 的其他阶段、MUST NOT 触碰 `WriteContext`

#### Scenario: 超 T 节点强制裂变（兜底）

- **WHEN** `changed_nodes` 中某节点层级视图超 `token_budget.T`
- **THEN** `run_compaction` MUST 强制运行 `CompactionPlugin`（忽略 `should_run`）使其收敛回 ≤ T
- **AND** 无 `CompactionPlugin` 时 MUST `logger.error` 显式暴露（不静默放任不变量破坏）

#### Scenario: 既有 ingest 守门不变

- **WHEN** `ingest` 执行阶段⑥
- **THEN** 行为 MUST 与既有完全一致（仍调 `_run_compaction`）；`run_compaction` 为新增 public 入口、不改动 `_run_compaction` 内部逻辑

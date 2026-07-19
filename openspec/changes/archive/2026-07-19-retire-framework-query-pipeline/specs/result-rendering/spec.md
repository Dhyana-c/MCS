# result-rendering Spec Delta — retire-framework-query-pipeline

## MODIFIED Requirements

### Requirement: 核心库提供共享结果渲染纯函数

`mcs.rendering` SHALL 提供共享纯函数 `format_ingest_status`（写管线 `ingest` 状态 → LLM 可读文本，供 `MemoryStore.learn` 复用）。**`render_query_result` REMOVED**——其为 `mcs.query()` 结果（`Subgraph` / str）渲染的唯一消费者是 `associate(mode="mcs")`，随 mode 删除与读查询退役而失去调用者（级联删除）。`Subgraph` 实体本身**保留**（`store` 层仍用，见下）。

#### Scenario: format_ingest_status 供 learn 复用

- **WHEN** `MemoryStore.learn` 渲染 ingest 状态
- **THEN** MUST 经 `format_ingest_status`

#### Scenario: 不再提供 render_query_result

- **WHEN** 检查 `mcs.rendering` 公开符号
- **THEN** MUST NOT 含 `render_query_result`（随读查询编排退役）

> 完整 requirement 正文 impl 期核定（剔除 render_query_result 分支，保留 format_ingest_status；`Subgraph` 实体保留因 `sqlite_store` / `in_memory` 的图视图方法仍返回它）。

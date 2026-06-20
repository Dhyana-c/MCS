# result-rendering（delta）

> `relation_model` 删除，`render_query_result` 不再接收该参数；`render_facts` 不再分模式。其余（ingest 状态摘要、公开 API 命名）不变。

## MODIFIED Requirements

### Requirement: 核心库提供共享结果渲染纯函数

核心库 SHALL 在 `mcs/rendering.py` 提供两个**公开纯函数**，把 MCS 查询 / 写入结果转为人 / LLM 可读文本，供应用层（`mcs_mcp`、`mcs_agent`）复用。这两个函数 MUST NOT 依赖任何应用包或 mcp SDK，仅依赖 `mcs.core.context_renderer` 与 `mcs.entities.graph`（依赖方向 `rendering → core`，无环）。

#### Scenario: query 结果渲染

- **WHEN** 调用 `render_query_result(result, plugin_manager)`
- **THEN** `result` 为 `str`（postprocess 已转换）MUST 原样透传
- **AND** `result` 为 `Subgraph` MUST 经 `ContextRenderer.render_facts(nodes, edges)` 渲染并返回文本（关系边 `主 — 宾`，无 `relation_model` 参数）
- **AND** 其余类型 MUST 兜底 `str(result)`，MUST NOT 返回原始对象 / 内部结构

#### Scenario: ingest 状态摘要

- **WHEN** 调用 `format_ingest_status(wctx)`
- **THEN** MUST 返回含抽取概念数（`len(wctx.concepts)`）、新增 / 合并节点数（`len(wctx.changed)`）、`persisted` 的简短字符串
- **AND** MUST NOT 返回原始 `WriteContext`、MUST NOT 报边计数

#### Scenario: 公开 API 命名

- **WHEN** 应用层引用这两个函数
- **THEN** MUST 从 `mcs.rendering` 导入公开名 `render_query_result` / `format_ingest_status`

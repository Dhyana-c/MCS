# mcs-builder Spec Delta — retire-framework-query-pipeline

## MODIFIED Requirements

### Requirement: MCS 类瘦门面设计

`MCS` 类 SHALL 只暴露**写管线 + 图原语只读入口**与定向插件管理：`ingest(data, **metadata)`（委托 `write_pipeline.ingest`）、`run_compaction(changed_nodes)`、`run_maintenance(force)`、`register_plugin` / `register_shared_plugin` / `unregister_plugin` / `get_plugin`、`show()`、`shutdown()`。**`query()` 方法删除**——读查询职责归记忆 agent，框架不再提供查询编排。`MCS` 仍持有 `query_engine`（图导航 + 遍历原语，供 `WritePipeline` 关联定位与 agent `MemoryStore` 复用），但其公共表面不再有 query 入口。

`MCS MUST NOT 持有 MCSConfig、MUST NOT 有 initialize()、MUST NOT 有 persist_full()`。

#### Scenario: MCS 构造不接受 Config

- **WHEN** 检查 `MCS.__init__` 参数签名
- **THEN** MUST NOT 包含 `config: MCSConfig`
- **AND** MUST 接受 `write_pipeline`, `query_engine`, `store`, `write_manager`, `read_manager`

#### Scenario: ingest 调用写入管线

- **WHEN** 调用 `mcs.ingest("some text")`
- **THEN** MUST 委托 `write_pipeline.ingest()`，返回 `WriteContext`

#### Scenario: MCS 不暴露 query 入口

- **WHEN** 检查 `MCS` 公共方法
- **THEN** MUST NOT 有 `query()` 方法；读查询 MUST 经记忆 agent 工具（`search`/`associate`/`reason`）驱动

> 原 "Scenario: query 调用查询管线"（委托 `query_engine.query()`）REMOVED。

---

### Requirement: show 方法以 Markdown 流程图展示双管线

`MCS.show()` SHALL 以 Markdown 展示**写管线**（① Preprocess → ② Related Nodes → ③ Extract → ④ Judge → ⑤ Apply → ⑥ Compaction → ⑦ Persist）与注册插件清单。**原 "Reader Pipeline" 5 阶段 mermaid 段 REMOVED**——读查询编排已退役，`QueryEngine` 不再有 ①-⑤ 管线可展示；`read_manager` 仍列出（供 ENTRY/TRIM/INDEX/LLM 等存活插件可观测）。

#### Scenario: 不展示 Reader Pipeline

- **WHEN** 调用 `MCS.show()`
- **THEN** 输出 MUST 含 Writer Pipeline mermaid 段与双 manager 插件清单；MUST NOT 含 "Reader Pipeline" / 读查询 5 阶段段

> 其余 scenario 正文 impl 期核定。

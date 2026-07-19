# phase1-defaults Spec Delta — retire-framework-query-pipeline

## MODIFIED Requirements

### Requirement: 知识图谱模式默认插件清单

`MCSConfig.knowledge_graph()` SHALL 返回含下列默认插件实例：`AliasIndexPlugin` (NodeExtension)、`AliasEntryPlugin` (EntryPlugin priority=100)、`HubFallbackEntryPlugin` (EntryPlugin priority=0)、`PriorityTrimPlugin` (Trim)、**`SummaryPlugin` (NodeExtension——管理 `extensions['summary']` 槽、由 `SummaryRegenPlugin` 再生，保留)**、`SourceTrackingPlugin` (NodeExtension)、`IdempotencyCheckPlugin` (**WritePreprocess**，写管线阶段 ①)、`FanoutReducerPlugin` (Compaction)、`SummaryRegenPlugin` (Compaction)、`GraphSummaryPlugin` (Maintenance)、`SQLiteStoragePlugin`、`DeepSeekLLMPlugin`。

**变更**：
- `SummaryPlugin` **保留**（虽位于 `mcs/plugins/postprocess/` 目录但实为 `NodeExtensionInterface` 子类、非 Postprocess——命名陷阱；删除会 corrupt 写管线 summary 槽）。
- `IdempotencyCheckPlugin` 标注校正：`WRITE_PREPROCESS`（写阶段 ①），**非** Postprocess（原 spec "Postprocess, on write stage ①" 为过时笔误）。
- `PluginType.ARBITRATION` / `POSTPROCESS` / `QUERY_PREPROCESS` 已删（见 plugin-protocol delta）→ 默认不再有这些类型的插件。

#### Scenario: 默认配置加载

- **WHEN** 加载 `MCSConfig.knowledge_graph()`
- **THEN** MUST 注册上述清单；MUST NOT 注册任何 `POSTPROCESS` / `ARBITRATION` / `QUERY_PREPROCESS` 插件（类型已删）；`SummaryPlugin` MUST 仍在清单中（NodeExtension）

> 原 "Scenario: 默认 ArbitrationPlugin 为空" 与 "Scenario: 默认 PostprocessPlugin 链（读流程 ⑤）为空" REMOVED——对应 PluginType 已不存在。

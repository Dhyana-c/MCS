# preprocess-plugin Spec Delta — retire-framework-query-pipeline

## MODIFIED Requirements

### Requirement: 废弃 PreprocessPluginInterface 的迁移指向

原 `PreprocessPluginInterface`（已废弃）的迁移指向 SHALL 仅保留 `WritePreprocessPluginInterface`（写管线阶段 ①）。原"迁移到 WritePreprocess / QueryPreprocess"的 `QueryPreprocess` 指向 REMOVED——`PluginType.QUERY_PREPROCESS` 与 `QueryPreprocessPluginInterface` 已删（见 plugin-protocol delta）。

#### Scenario: 废弃指向不含 QueryPreprocess

- **WHEN** 检查 `PreprocessPluginInterface` 废弃说明
- **THEN** MUST 仅指向 `WritePreprocessPluginInterface`；MUST NOT 提及已删除的 `QueryPreprocessPluginInterface`

> 完整 requirement 正文（含原废弃 scenario）impl 期对照现行 spec 核定。

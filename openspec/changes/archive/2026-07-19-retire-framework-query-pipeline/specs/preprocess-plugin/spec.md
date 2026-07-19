# preprocess-plugin Spec Delta — retire-framework-query-pipeline

> 本 capability 定义前置插件接口（`PreprocessPluginInterface` / `PluginType.PREPROCESS`）。读查询编排退役后，**查询管线阶段 ① 不再消费前置插件**——`QueryEngine._run_preprocess` 收敛为纯 `return text` 透传（`PluginType.QUERY_PREPROCESS` 已删、无插件链可遍历），作为 `locate_seeds` 的内部细节存活（见 lightweight-query delta）。Purpose 从"查询和写入管线的文本预处理"**收敛为"写入管线的文本预处理"**。
>
> `PreprocessPluginInterface` 废弃后的迁移指向（去 `QueryPreprocessPluginInterface`）由 `plugin-protocol` delta 的「废弃 PreprocessPluginInterface」MODIFIED 承载（该 requirement 本身归 plugin-protocol capability）；本 capability 不重复。

## REMOVED Requirements

### Requirement: 查询管线阶段 ① 使用 PreprocessPlugin 类型

读查询管线退役（见 query-pipeline delta）→ `QueryEngine._run_preprocess` 不再遍历任何前置插件链（方法体收敛为 `return text`）。该 requirement 描述的"查询管线 ① 使用 PreprocessPlugin"已不成立，整体 REMOVED。

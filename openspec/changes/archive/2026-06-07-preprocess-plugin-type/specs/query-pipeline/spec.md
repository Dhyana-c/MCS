# query-pipeline Specification Delta

## ADDED Requirements

### Requirement: 阶段 ① 使用独立的 PreprocessPlugin 类型

The system SHALL modify stage ① (前置插件链) to use `PluginType.PREPROCESS` for locating plugins, instead of filtering `PostprocessPlugin` by `position` attribute.

#### Scenario: 前置插件类型独立

- **WHEN** 查询管线执行阶段 ①
- **THEN** 框架 MUST 通过 `plugin_manager.get_all(PluginType.PREPROCESS)` 获取前置插件链

#### Scenario: 前置插件处理文本

- **WHEN** 前置插件链执行
- **THEN** 每个插件的输入和输出 MUST 是 `str` 类型

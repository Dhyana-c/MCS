## ADDED Requirements

### Requirement: presets 模块提供 Phase1 默认构建器

`mcs/presets/phase1.py` SHALL 提供 `Phase1Builder` 类，继承 `MCSBuilder`，实现 Phase1 插件注册表查找。

#### Scenario: Phase1Builder 查找插件类

- **WHEN** 调用 `Phase1Builder(config).get_plugin_class("alias_index")`
- **THEN** MUST 返回 `AliasIndexPlugin` 类

#### Scenario: Phase1Builder 构建完整实例

- **WHEN** 调用 `Phase1Builder(config).build()`
- **THEN** MUST 返回已完成 `initialize()` 的 MCS 实例

### Requirement: presets 模块提供快捷工厂函数

`mcs/presets/phase1.py` SHALL 提供 `create_mcs()` 函数，接受常用参数（`llm`、`db_path`、`token_budget` 等），返回已初始化的 MCS 实例。

#### Scenario: 一键创建 MCS

- **WHEN** 调用 `create_mcs(llm="deepseek", db_path="test.db")`
- **THEN** MUST 返回已初始化的 MCS 实例，使用 Phase1 默认插件和指定配置

#### Scenario: 快捷工厂配置覆盖

- **WHEN** 调用 `create_mcs(token_budget=16000)`
- **THEN** 返回的 MCS 实例 MUST 使用 16000 作为 token_budget

### Requirement: presets 模块提供插件注册表函数

`mcs/presets/phase1.py` SHALL 提供 `get_phase1_plugin_registry() -> dict[str, type[Plugin]]` 函数，返回 Phase1 全部插件类映射。

#### Scenario: 注册表完整性

- **WHEN** 调用 `get_phase1_plugin_registry()`
- **THEN** 返回的字典 MUST 包含当前 `_default_plugin_registry()` 中的全部插件条目

### Requirement: 向后兼容别名

`mcs/__init__.py` SHALL 将 `_default_plugin_registry` 设为 `get_phase1_plugin_registry` 的别名，保持旧代码兼容。

#### Scenario: 旧导入路径兼容

- **WHEN** 使用 `from mcs import _default_plugin_registry`
- **THEN** MUST 返回 `mcs.presets.phase1.get_phase1_plugin_registry`
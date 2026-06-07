## ADDED Requirements

### Requirement: PluginManager 支持注销插件

`PluginManager` SHALL 提供 `unregister(name: str) -> bool` 方法，用于移除已注册的插件。

#### Scenario: unregister 成功移除插件

- **WHEN** 调用 `manager.unregister("existing_plugin")` 且该插件已注册
- **THEN** MUST 从 `manager._plugins` 中移除该插件
- **AND** MUST 从 `manager._by_type` 的所有相关类型列表中移除该插件
- **AND** MUST 返回 `True`

#### Scenario: unregister 插件不存在

- **WHEN** 调用 `manager.unregister("nonexistent")`
- **THEN** MUST 返回 `False`
- **AND** MUST NOT 抛出异常

---

## MODIFIED Requirements

### Requirement: MCS 类双 PluginManager 架构

`MCS` 类 SHALL 维护 `write_manager` 和 `read_manager` 两个 `PluginManager`。插件注册/注销 MUST 通过 `register_plugin(plugin, target)` / `unregister_plugin(name, target)` 方法指定目标管线，MUST NOT 支持双注册。

#### Scenario: 共享插件由 Builder 在构建时双注册

- **WHEN** Builder 处理 `config.shared_plugins`
- **THEN** 共享插件 MUST 以同一 Python 对象实例注册到 `write_manager` 和 `read_manager`
- **AND** `write_manager.get_by_name(name) is read_manager.get_by_name(name)` MUST 为 True

#### Scenario: 运行时注册必须指定目标管线

- **WHEN** 调用 `mcs.register_plugin(plugin, target="writer")`
- **THEN** 插件 MUST 只注册到 `write_manager`
- **AND** `read_manager.get_by_name(plugin.get_name())` MUST 返回 `None`

#### Scenario: QueryEngine 使用 read_manager

- **WHEN** MCS 持有 QueryEngine
- **THEN** QueryEngine MUST 使用 `read_manager` 和 `read_llm`

#### Scenario: WritePipeline 使用 write_manager 但 query_engine 用读取的

- **WHEN** MCS 持有 WritePipeline
- **THEN** WritePipeline 的 `plugin_manager` MUST 是 `write_manager`
- **AND** WritePipeline 的 `llm` MUST 是 `write_llm`
- **AND** WritePipeline 的 `query_engine` MUST 是使用 `read_manager` 的 QueryEngine

---

## REMOVED Requirements

### Requirement: register_plugin 双注册

**Reason**: 运行时注册必须明确指定目标管线（writer/reader），不再支持隐式双注册。共享插件由 Builder 在构建时处理。

**Migration**: 旧 `mcs.register_plugin(plugin)` 改为：
- `mcs.register_shared_plugin(plugin)` —— 共享到两侧
- 或 `mcs.register_plugin(plugin, target="writer")` + `mcs.register_plugin(plugin, target="reader")` —— 显式两次调用
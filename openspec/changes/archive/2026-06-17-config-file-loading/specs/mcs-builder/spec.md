## MODIFIED Requirements

### Requirement: MCSBuilder 通过抽象方法查找插件类

`MCSBuilder` SHALL 定义抽象方法 `get_plugin_class(name: str) -> type[Plugin] | None`，由子类实现具体插件查找逻辑（基类**不**提供默认实现）。框架默认构建器 `Phase1Builder.get_plugin_class` SHALL 在内置注册表（`get_phase1_plugin_registry()`）未命中时支持 **import-path 回退**：

- name 形如 `module:attr` 时经 `import_from_path` 解析为插件类，结果 MUST 是 `Plugin` 子类（否则报错）；
- 无 `:` 的未知名 SHALL 返回 `None`（"未知名跳过、不抛异常"逐字保留）；
- `module:attr` 形但解析失败（模块 / 属性不存在或非 `Plugin` 子类）SHALL 抛清晰错误（用户配置错误，不静默吞）。

#### Scenario: 插件类查找委托给子类

- **WHEN** `MCSBuilder.build()` 处理插件列表中的每个名称
- **THEN** MUST 调用 `self.get_plugin_class(name)` 查找插件类
- **AND** 返回 None 的名称 MUST 被跳过

#### Scenario: 未知插件名不报错

- **WHEN** `Phase1Builder.get_plugin_class("nonexistent")`（无 `:` 的未知名）返回 None
- **THEN** Builder MUST 跳过该插件名继续构建
- **AND** MUST NOT 抛出异常

#### Scenario: 内置名仍走内置注册表

- **WHEN** `Phase1Builder.get_plugin_class("fanout_reducer")`（内置名）
- **THEN** MUST 返回内置注册表中的对应类（import-path 回退 MUST 仅在内置未命中时触发）

#### Scenario: import-path 名解析外部插件

- **WHEN** `Phase1Builder.get_plugin_class("my_pkg.exts:MyEdgeExt")` 且该类存在且是 `Plugin` 子类
- **THEN** MUST 经 import-path 解析并返回该类

#### Scenario: import-path 解析失败抛错

- **WHEN** name 形如 `module:attr` 但模块 / 属性不存在或非 `Plugin` 子类
- **THEN** MUST 抛清晰错误（含原始 name）；MUST NOT 静默返回 None（与"无 `:` 的未知名"区分）

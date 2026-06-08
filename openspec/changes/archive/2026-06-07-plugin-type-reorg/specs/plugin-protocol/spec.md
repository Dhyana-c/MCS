## MODIFIED Requirements

### Requirement: Plugin 顶级基类定义于 core/plugin.py

The system SHALL define a top-level `Plugin` abstract base class in `mcs/core/plugin.py` as the single root abstraction for all plugins. 所有接口与插件实现 SHALL 适配它；旧的 `mcs/plugins/base.py` 基类 SHALL 被删除，其职责由 `core/plugin.py` 接管。插件实现文件 SHALL 按其 `PluginType` 组织在 `mcs/plugins/<type>/` 目录下，而非 `mcs/plugins/phase1/`。

#### Scenario: Plugin 契约完整

- **WHEN** 检查 `mcs/core/plugin.py`
- **THEN** MUST 含 `Plugin` 类，具有抽象方法 `get_name() -> str`、`get_type() -> PluginType`、`execute(**kwargs) -> Any`
- **AND** MUST 提供具默认实现的 `get_types() -> set[PluginType]`（默认 `{get_type()}`）、`get_priority() -> int`（默认 0）、`initialize(context) -> None`（空操作）、`shutdown() -> None`（空操作）

#### Scenario: 旧基类不存在

- **WHEN** 检查 `mcs/plugins/base.py`
- **THEN** 该文件 MUST NOT 存在
- **AND** 任何模块 MUST NOT 从 `mcs.plugins.base` 导入 `Plugin`

#### Scenario: 插件按类型目录组织

- **WHEN** 检查 `mcs/plugins/` 目录结构
- **THEN** MUST NOT 存在 `phase1/` 或 `phase2/` 子目录
- **AND** 插件文件 MUST 位于 `mcs/plugins/<plugin_type>/` 对应目录下

---

### Requirement: PluginType 类型枚举

The system SHALL define a `PluginType` enum in `mcs/core/plugin.py`, inheriting `str` and `Enum`, enumerating all plugin roles. PluginManager 与管线代码 SHALL 用它作为索引与查找键，取代旧的 interface 类对象。插件目录结构 SHALL 与 `PluginType` 枚举值对齐。

#### Scenario: PluginType 取值完整

- **WHEN** 检查 `PluginType`
- **THEN** MUST 继承 `str` 与 `Enum`
- **AND** MUST 含取值 ENTRY、TRIM、ARBITRATION、PREPROCESS、POSTPROCESS、COMPACTION、INDEX、LLM、NODE_EXTENSION、STORAGE_SCHEMA_EXT、MAINTENANCE、SEED_SELECTOR

#### Scenario: 管线按 PluginType 查找

- **WHEN** 检查 `core/write_pipeline.py`、`core/query_engine.py`、`core/context_renderer.py`
- **THEN** 所有 `plugin_manager.get()` / `get_all()` 调用 MUST 使用 `PluginType.XXX` 参数，而非 interface 类对象

#### Scenario: 目录名与 PluginType 对齐

- **WHEN** 检查 `mcs/plugins/` 下的子目录名
- **THEN** 每个子目录名 MUST 对应 `PluginType` 的一个小写枚举值（如 `entry` 对应 `ENTRY`）

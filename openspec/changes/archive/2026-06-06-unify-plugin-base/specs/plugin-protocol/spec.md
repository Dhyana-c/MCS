## ADDED Requirements

### Requirement: Plugin 顶级基类定义于 core/plugin.py

The system SHALL define a top-level `Plugin` abstract base class in `mcs/core/plugin.py` as the single root abstraction for all plugins. 所有接口与插件实现 SHALL 适配它；旧的 `mcs/plugins/base.py` 基类 SHALL 被删除，其职责由 `core/plugin.py` 接管。

#### Scenario: Plugin 契约完整

- **WHEN** 检查 `mcs/core/plugin.py`
- **THEN** MUST 含 `Plugin` 类，具有抽象方法 `get_name() -> str`、`get_type() -> PluginType`、`execute(**kwargs) -> Any`
- **AND** MUST 提供具默认实现的 `get_types() -> set[PluginType]`（默认 `{get_type()}`）、`get_priority() -> int`（默认 0）、`initialize(context) -> None`（空操作）、`shutdown() -> None`（空操作）

#### Scenario: 旧基类不存在

- **WHEN** 检查 `mcs/plugins/base.py`
- **THEN** 该文件 MUST NOT 存在
- **AND** 任何模块 MUST NOT 从 `mcs.plugins.base` 导入 `Plugin`

---

### Requirement: PluginType 类型枚举

The system SHALL define a `PluginType` enum in `mcs/core/plugin.py`, inheriting `str` and `Enum`, enumerating all plugin roles. PluginManager 与管线代码 SHALL 用它作为索引与查找键，取代旧的 interface 类对象。

#### Scenario: PluginType 取值完整

- **WHEN** 检查 `PluginType`
- **THEN** MUST 继承 `str` 与 `Enum`
- **AND** MUST 含取值 ENTRY、TRIM、ARBITRATION、POSTPROCESS、COMPACTION、STORAGE、INDEX、LLM、NODE_EXTENSION、STORAGE_SCHEMA_EXT、MAINTENANCE

#### Scenario: 管线按 PluginType 查找

- **WHEN** 检查 `core/write_pipeline.py`、`core/query_engine.py`、`core/context_renderer.py`
- **THEN** 所有 `plugin_manager.get()` / `get_all()` 调用 MUST 使用 `PluginType.XXX` 参数，而非 interface 类对象

---

### Requirement: 接口层继承 Plugin 且不反向依赖 core 管理器

所有接口（`EntryPluginInterface` 等）SHALL 继承 `core/plugin.py` 的 `Plugin`，实现 `get_type()` 返回对应 `PluginType`，并以 `execute()` 委托其核心方法。接口层 SHALL NOT 依赖 `core/plugin_manager`。

#### Scenario: 接口继承 Plugin

- **WHEN** 检查任意接口文件（如 `interfaces/entry_plugin.py`）
- **THEN** 该接口类 MUST 继承 `Plugin`
- **AND** MUST 实现 `get_type()` 返回对应 `PluginType`
- **AND** MUST 以 `execute()` 委托其核心方法（无统一执行语义者 MAY 抛 `NotImplementedError`）

#### Scenario: 接口不导入 plugin_manager

- **WHEN** 检查 `interfaces/` 下所有文件的非 TYPE_CHECKING 导入
- **THEN** MUST NOT 导入 `mcs.core.plugin_manager`

---

### Requirement: 多接口插件通过 get_types 登记全部类型

实现多个接口的插件 SHALL 覆写 `get_types()` 返回其全部 `PluginType`，使 PluginManager 能按其中任意类型索引到它；`PluginManager.register()` SHALL 按 `get_types()` 把插件登记到每个类型下。

#### Scenario: 多接口插件可被每个类型查找

- **WHEN** 一个插件同时实现 NodeExtension 与 StorageSchemaExtension（如 SourceTracking），其 `get_types()` 返回 `{NODE_EXTENSION, STORAGE_SCHEMA_EXT}`
- **THEN** `plugin_manager.get_all(PluginType.NODE_EXTENSION)` 与 `get_all(PluginType.STORAGE_SCHEMA_EXT)` MUST 都能返回该插件

#### Scenario: 单接口插件默认行为

- **WHEN** 一个插件未覆写 `get_types()`
- **THEN** `get_types()` MUST 返回 `{get_type()}`

---

### Requirement: core 不依赖 interfaces（单向依赖）

依赖关系 SHALL 满足单向原则：`core` 不依赖 `interfaces`。`PluginManager` SHALL 仅依赖 `core/plugin.py`，按 `PluginType` 索引，不含任何按 interface 类的 `isinstance` 收集逻辑。

#### Scenario: core 不在运行时导入 interfaces

- **WHEN** 检查 `mcs/core/` 下所有 `.py` 文件
- **THEN** 非 TYPE_CHECKING 块内 MUST NOT 导入 `mcs.interfaces`

#### Scenario: PluginManager 无接口特化收集方法

- **WHEN** 检查 `core/plugin_manager.py`
- **THEN** MUST NOT 含 `collect_schema_extensions()` / `collect_node_extensions()` 等按 interface 类 `isinstance` 筛选的方法
- **AND** 此类收集 SHALL 由调用方用 `get_all(PluginType.X)` 完成

---

## MODIFIED Requirements

### Requirement: 提供 EntryPluginInterface 用于种子定位

The system SHALL define `EntryPluginInterface` inheriting `Plugin`, with: `get_type()` returning `PluginType.ENTRY`, a `get_priority() -> int` method (descending = higher priority), an `exclusive` property (default False), and an abstract `locate(query: str, ctx) -> List[Node]` method. `execute()` SHALL delegate to `locate()`.

#### Scenario: 接口最小契约

- **WHEN** 实现一个 EntryPlugin
- **THEN** 子类 MUST 提供 `get_priority()`、`exclusive`、`locate` 三个成员；`locate` MUST 返回 `List[Node]`；`get_type()` MUST 返回 `PluginType.ENTRY`

#### Scenario: priority 决定合并顺序

- **WHEN** 框架合并多个 EntryPlugin 的输出
- **THEN** 合并结果 MUST 按 `get_priority()` 降序排列；同 priority 的相对顺序由注册顺序决定

#### Scenario: exclusive 短路语义

- **WHEN** 高优先级插件返回非空且 `exclusive=True`
- **THEN** 框架 MUST 不调用比它优先级低的 EntryPlugin

---

### Requirement: 插件优先级排序与短路语义统一

For any plugin chain that supports priority (entry plugins, postprocess plugins), the system SHALL use the same semantics: priority obtained via `get_priority()` (descending order); tie-breaking by registration order; explicit `exclusive=True` on EntryPlugin short-circuits lower priorities; no implicit short-circuiting elsewhere.

#### Scenario: 同种插件链语义一致

- **WHEN** 实现 EntryPlugin chain 与 Postprocess chain
- **THEN** 两者 MUST 使用相同排序规则（`get_priority()` 降序）；MUST 仅 EntryPlugin 支持 `exclusive=True`（Postprocess 是串联管道而非选择器）

#### Scenario: 同 priority 行为稳定

- **WHEN** 两个插件 priority 相同
- **THEN** 框架 MUST 在同一配置下产生相同执行顺序；具体顺序由注册顺序决定（先注册者先执行）

---

### Requirement: PluginManager 支持新插件接口的注册与查找

`PluginManager` SHALL register and look up plugins by `PluginType` enum (not by interface class object). 它 SHALL 按 `plugin.get_types()` 把插件登记到每个类型下，并对需要排序的类型按 `get_priority()` 降序返回。

#### Scenario: 按类型查找

- **WHEN** 调用 `plugin_manager.get_all(PluginType.ENTRY)`
- **THEN** 返回值 MUST 是按 `get_priority()` 降序排列的所有 ENTRY 类型插件
- **AND** `plugin_manager.get(PluginType.ENTRY)` MUST 返回其中第一个（无则 None）

#### Scenario: 按名称查找

- **WHEN** 调用 `plugin_manager.get_by_name(name)`
- **THEN** MUST 返回该名称的插件实例（无则 None）

#### Scenario: ArbitrationPlugin 单例检查

- **WHEN** 注册第二个 `get_types()` 含 `PluginType.ARBITRATION` 的插件
- **THEN** PluginManager MUST 在 `register` 时抛 `ConfigurationError`

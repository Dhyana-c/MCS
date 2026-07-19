# plugin-protocol Spec Delta — retire-framework-query-pipeline

> 删除三个**仅服务读查询管线**的插件接口与对应 `PluginType` 枚举值。ENTRY / TRIM / WRITE_PREPROCESS / INDEX / LLM / NODE_EXTENSION / EDGE_EXTENSION / STORAGE_SCHEMA_EXT / COMPACTION / MAINTENANCE 接口**全部保留**（locate_seeds 仍用 ENTRY+TRIM）。

## REMOVED Requirements

### Requirement: 提供 ArbitrationPluginInterface 用于读流程仲裁

`ArbitrationPluginInterface` 与 `PluginType.ARBITRATION` 删除（零实现；互斥裁决由记忆 agent `arbitrate` 工具 `purpose=adjudicate` 承担，不经框架管线）。

### Requirement: 提供 QueryPreprocessPluginInterface 用于查询管线前置处理

`QueryPreprocessPluginInterface` 与 `PluginType.QUERY_PREPROCESS` 删除（presets 零注册、纯 no-op 透传；写侧 `WRITE_PREPROCESS` 不受影响）。

### Requirement: 提供 PostprocessPluginInterface 用于后置处理

`PostprocessPluginInterface` 与 `PluginType.POSTPROCESS` 删除（仅被 `query()` ⑤ 调用；`RerankPlugin` 实现随之删除）。**注**：`SummaryPlugin` 虽位于 `mcs/plugins/postprocess/` 但实为 `NodeExtensionInterface` 子类——**保留**（见 phase1-defaults delta）。`WritePipeline` 的 ① 前置链用的是 `WRITE_PREPROCESS`，非本接口（`write_pipeline.py:7` docstring 的"PostprocessPlugin chain"为过时笔误，代码实际走 WRITE_PREPROCESS）。

## MODIFIED Requirements

### Requirement: 废弃 PreprocessPluginInterface

`PreprocessPluginInterface` 废弃后的迁移指向 SHALL 仅保留 `WritePreprocessPluginInterface`。原指向 `QueryPreprocessPluginInterface` REMOVED（随 `PluginType.QUERY_PREPROCESS` 删除）。

#### Scenario: 废弃指向不含 QueryPreprocess

- **WHEN** 检查 `PreprocessPluginInterface` 废弃说明
- **THEN** MUST 仅指向 `WritePreprocessPluginInterface`；MUST NOT 提及 `QueryPreprocessPluginInterface`

---

### Requirement: PluginType 类型枚举

The system SHALL define a `PluginType` enum in `mcs/core/plugin.py`, inheriting `str` and `Enum`, enumerating all plugin roles. PluginManager 与管线代码 SHALL 用它作为索引与查找键，取代旧的 interface 类对象。

> retire-framework-query-pipeline 删除 `ARBITRATION` / `POSTPROCESS` / `QUERY_PREPROCESS` 三个枚举值（对应接口随读查询编排退役）。

#### Scenario: PluginType 取值完整

- **WHEN** 检查 `PluginType`
- **THEN** MUST 继承 `str` 与 `Enum`
- **AND** MUST 含取值 ENTRY、TRIM、WRITE_PREPROCESS、COMPACTION、INDEX、LLM、NODE_EXTENSION、EDGE_EXTENSION、STORAGE_SCHEMA_EXT、MAINTENANCE
- **AND** MAY 含废弃值 PREPROCESS（指向 WRITE_PREPROCESS）
- **AND** MUST NOT 含 `ARBITRATION` / `POSTPROCESS` / `QUERY_PREPROCESS`（随读查询编排退役删除）

#### Scenario: 管线按 PluginType 查找

- **WHEN** 检查 `core/write_pipeline.py`、`core/query_engine.py`、`core/context_renderer.py`
- **THEN** 所有 `plugin_manager.get()` / `get_all()` 调用 MUST 使用 `PluginType.XXX` 参数，而非 interface 类对象

#### Scenario: 目录名与 PluginType 对齐

- **WHEN** 检查 `mcs/plugins/` 下的子目录名
- **THEN** 每个子目录名 MUST 对应 `PluginType` 的一个小写枚举值（如 `entry` 对应 `ENTRY`）
- **AND** MUST NOT 存在 `arbitration` / `postprocess`（含 rerank）/ `query_preprocess` 子目录（随类型删除；`postprocess/` 仅留 `summary.py`——SummaryPlugin 实为 NodeExtension，目录名保留属历史命名）

---

### Requirement: PluginManager 支持新插件接口的注册与查找

`PluginManager` SHALL register and look up plugins by `PluginType` enum (not by interface class object). 它 SHALL 按 `plugin.get_types()` 把插件登记到每个类型下，并对需要排序的类型按 `get_priority()` 降序返回。

> retire-framework-query-pipeline 删除 `ArbitrationPlugin 单例强制` 逻辑——`PluginType.ARBITRATION` 已删，无仲裁插件可注册，单例检查随之失效。

#### Scenario: 按类型查找

- **WHEN** 调用 `plugin_manager.get_all(PluginType.ENTRY)`
- **THEN** 返回值 MUST 是按 `get_priority()` 降序排列的所有 ENTRY 类型插件
- **AND** `plugin_manager.get(PluginType.ENTRY)` MUST 返回其中第一个（无则 None）

#### Scenario: 按名称查找

- **WHEN** 调用 `plugin_manager.get_by_name(name)`
- **THEN** MUST 返回该名称的插件实例（无则 None）

> 原 "Scenario: ArbitrationPlugin 单例检查" REMOVED（`PluginType.ARBITRATION` 删除，无仲裁插件可注册，单例检查代码随之删除）。

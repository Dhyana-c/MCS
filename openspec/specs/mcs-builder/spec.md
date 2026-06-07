# mcs-builder Specification

## Purpose
TBD - created by archiving change mcs-builder-abstraction. Update Purpose after archive.

## Requirements

### Requirement: MCSConfig 支持读写分离插件配置

`MCSConfig` SHALL 使用 `shared_plugins`、`write_plugins`、`read_plugins` 三个列表替代旧的 `plugins` 列表，并用 `write_llm`、`read_llm` 分别指定写入和读取的 LLM。

#### Scenario: shared_plugins 注册到两个 manager

- **WHEN** `MCS.initialize()` 处理 `config.shared_plugins`
- **THEN** 每个共享插件 MUST 以同一实例注册到 `write_manager` 和 `read_manager`

#### Scenario: write_plugins 只注册到 write_manager

- **WHEN** `MCS.initialize()` 处理 `config.write_plugins`
- **THEN** 每个写入插件 MUST 只注册到 `write_manager`，MUST NOT 注册到 `read_manager`

#### Scenario: read_plugins 只注册到 read_manager

- **WHEN** `MCS.initialize()` 处理 `config.read_plugins`
- **THEN** 每个读取插件 MUST 只注册到 `read_manager`，MUST NOT 注册到 `write_manager`

#### Scenario: LLM 分离

- **WHEN** `config.write_llm` 和 `config.read_llm` 指定不同值（如 `"ollama_llm"` 和 `"deepseek_llm"`）
- **THEN** `write_manager` MUST 包含 `write_llm` 对应的插件，`read_manager` MUST 包含 `read_llm` 对应的插件

#### Scenario: LLM 共用

- **WHEN** `config.write_llm` 和 `config.read_llm` 指定相同值
- **THEN** 该 LLM 插件 MUST 以同一实例注册到两个 manager

---

### Requirement: MCSBuilder 抽象基类定义构建契约

`MCSBuilder` SHALL 作为抽象基类定义在 `mcs/core/builder.py`，只依赖 `MCSConfig` 和 `Plugin` 类型。它 SHALL 提供 `build() -> MCS` 方法，封装从配置到初始化完成的整个构建流程。

#### Scenario: Builder 只依赖 core 类型

- **WHEN** 检查 `mcs/core/builder.py` 的非 TYPE_CHECKING 导入
- **THEN** MUST 只导入 `mcs/core/` 下的模块，MUST NOT 导入 `mcs/plugins/` 或 `mcs/presets/`

#### Scenario: Builder 构建完整 MCS 实例

- **WHEN** 调用 `builder.build()` 返回 MCS 实例
- **THEN** 返回的实例 MUST 已完成 `initialize()`，可直接调用 `ingest()` 和 `query()`

#### Scenario: Builder 从 shared/write/read 收集注册表

- **WHEN** `MCSBuilder._collect_registry()` 被调用
- **THEN** MUST 合并 `config.shared_plugins`、`config.write_plugins`、`config.read_plugins` 以及 `write_llm`/`read_llm` 中的所有插件名称，返回完整的名称→类映射

---

### Requirement: MCSBuilder 通过抽象方法查找插件类

`MCSBuilder` SHALL 定义抽象方法 `get_plugin_class(name: str) -> type[Plugin] | None`，由子类实现具体插件查找逻辑。`build()` SHALL 通过此方法为每个插件名称查找对应插件类。

#### Scenario: 插件类查找委托给子类

- **WHEN** `MCSBuilder.build()` 处理插件列表中的每个名称
- **THEN** MUST 调用 `self.get_plugin_class(name)` 查找插件类
- **AND** 返回 None 的名称 MUST 被跳过

---

### Requirement: MCS 类双 PluginManager 架构

`MCS` 类 SHALL 维护 `write_manager` 和 `read_manager` 两个 `PluginManager`，按 `MCSConfig` 的 shared/write/read 分类注册插件。

#### Scenario: 共享插件同实例双注册

- **WHEN** `MCS.initialize()` 注册共享插件
- **THEN** 共享插件 MUST 以同一 Python 对象实例注册到 `write_manager` 和 `read_manager`
- **AND** `write_manager.get_by_name(name) is read_manager.get_by_name(name)` MUST 为 True

#### Scenario: 专用插件单侧注册

- **WHEN** `MCS.initialize()` 注册写入专用插件
- **THEN** `write_manager.get_by_name(name)` MUST 返回该插件
- **AND** `read_manager.get_by_name(name)` MUST 返回 None

#### Scenario: QueryEngine 使用 read_manager

- **WHEN** `MCS.initialize()` 创建 `QueryEngine`
- **THEN** QueryEngine MUST 使用 `read_manager` 和 `read_llm`

#### Scenario: WritePipeline 使用 write_manager 但 query_engine 用读取的

- **WHEN** `MCS.initialize()` 创建 `WritePipeline`
- **THEN** WritePipeline 的 `plugin_manager` MUST 是 `write_manager`
- **AND** WritePipeline 的 `llm` MUST 是 `write_llm`
- **AND** WritePipeline 的 `query_engine` MUST 是使用 `read_manager` 的 QueryEngine

---

### Requirement: MCS 类位于 mcs/core/mcs.py

`MCS` 类 SHALL 定义在 `mcs/core/mcs.py`。`mcs/__init__.py` SHALL 从 `mcs.core.mcs` 导入并导出 `MCS`。

#### Scenario: 导入路径

- **WHEN** 使用 `from mcs import MCS`
- **THEN** MUST 正常工作，返回 `mcs.core.mcs.MCS` 类

#### Scenario: core 不依赖 plugins

- **WHEN** 检查 `mcs/core/mcs.py` 的非 TYPE_CHECKING 导入
- **THEN** MUST NOT 导入 `mcs/plugins/` 或 `mcs/presets/`

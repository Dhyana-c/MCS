# mcs-builder Specification

## Purpose

定义 MCS 实例的构建契约：Builder 全量组装、MCS 瘦门面、双 PluginManager 架构、插件注册/注销 API。
## Requirements
### Requirement: MCSConfig 支持读写分离插件配置

`MCSConfig` SHALL 使用 `shared_plugins`、`write_plugins`、`read_plugins` 三个列表替代旧的 `plugins` 列表，并用 `write_llm`、`read_llm` 分别指定写入和读取的 LLM。

#### Scenario: shared_plugins 注册到两个 manager

- **WHEN** `MCSBuilder.build()` 处理 `config.shared_plugins`
- **THEN** 每个共享插件 MUST 以同一实例注册到 `write_manager` 和 `read_manager`

#### Scenario: write_plugins 只注册到 write_manager

- **WHEN** `MCSBuilder.build()` 处理 `config.write_plugins`
- **THEN** 每个写入插件 MUST 只注册到 `write_manager`，MUST NOT 注册到 `read_manager`

#### Scenario: read_plugins 只注册到 read_manager

- **WHEN** `MCSBuilder.build()` 处理 `config.read_plugins`
- **THEN** 每个读取插件 MUST 只注册到 `read_manager`，MUST NOT 注册到 `write_manager`

#### Scenario: LLM 分离

- **WHEN** `config.write_llm` 和 `config.read_llm` 指定不同值（如 `"ollama_llm"` 和 `"deepseek_llm"`）
- **THEN** `write_manager` MUST 包含 `write_llm` 对应的插件，`read_manager` MUST 包含 `read_llm` 对应的插件

#### Scenario: LLM 共用

- **WHEN** `config.write_llm` 和 `config.read_llm` 指定相同值
- **THEN** 该 LLM 插件 MUST 以同一实例注册到两个 manager

---

### Requirement: MCSBuilder 抽象基类定义构建契约

`MCSBuilder` SHALL 作为抽象基类定义在 `mcs/core/builder.py`，只依赖 `MCSConfig` 和 `Plugin` 类型。它 SHALL 提供 `build() -> MCS` 方法，封装从配置到完成态 MCS 的完整构建流程（不再委托 `MCS.initialize()`）。

#### Scenario: Builder 只依赖 core 类型

- **WHEN** 检查 `mcs/core/builder.py` 的非 TYPE_CHECKING 导入
- **THEN** MUST 只导入 `mcs/core/` 下的模块，MUST NOT 导入 `mcs/plugins/` 或 `mcs/presets/`

#### Scenario: Builder 构建完成态 MCS 实例

- **WHEN** 调用 `builder.build()` 返回 MCS 实例
- **THEN** 返回的实例 MUST 已完成全部初始化，可直接调用 `ingest()` 和 `query()`
- **AND** MUST NOT 有 `initialize()` 方法可调用

#### Scenario: Builder 从 shared/write/read 收集注册表

- **WHEN** `MCSBuilder._collect_registry()` 被调用
- **THEN** MUST 合并 `config.shared_plugins`、`config.write_plugins`、`config.read_plugins` 以及 `write_llm`/`read_llm` 中的所有插件名称，返回完整的名称→类映射

---

### Requirement: Builder 执行完整组装流程

`MCSBuilder.build()` SHALL 执行以下完整流程并返回即用的 MCS 实例：

1. 实例化 Store（根据 config）
2. 实例化 TokenBudget
3. 实例化双 PluginManager（write_manager / read_manager）
4. 按 shared/write/read 分类实例化并注册插件
5. 处理 LLM 分离逻辑
6. 初始化 SQLiteStore（schema_extensions + node_extensions）
7. 创建 ContextRenderer（传入 read_manager，用于 PluginContext）
8. 构建 PluginContext 并初始化所有插件
9. 应用 prompt_overrides 到 LLM
10. 构建 QueryEngine（read_manager + read_llm）
11. 构建 WritePipeline（write_manager + write_llm + query_engine）
12. 构建 MCS（传入已组装好的所有组件）
13. 执行 load-on-startup（若 Store 为空且 SQLiteStore 可用）
14. 返回 MCS 实例

#### Scenario: build 返回的 MCS 可直接使用

- **WHEN** 调用 `builder.build()` 返回 MCS 实例
- **THEN** 返回的实例 MUST 可直接调用 `ingest()` 和 `query()`
- **AND** MUST NOT 需要额外调用 `initialize()`

#### Scenario: build 中共享插件双注册

- **WHEN** config.shared_plugins 包含插件名称
- **THEN** Builder MUST 以同一实例注册到 write_manager 和 read_manager
- **AND** `write_manager.get_by_name(name) is read_manager.get_by_name(name)` MUST 为 True

#### Scenario: build 中 load-on-startup

- **WHEN** Store 为空且 SQLiteStore 有持久化数据
- **THEN** Builder MUST 从 SQLite 加载已有数据
- **AND** MUST 重建所有 Index 插件

---

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

### Requirement: MCS 类瘦门面设计

`MCS` 类 SHALL 只暴露以下公共方法：
- `ingest(text: str, **metadata) -> WriteContext`：执行写入管线
- `query(text: str, existing_context: list | None = None) -> Any`：执行查询管线
- `show() -> str`：以 Markdown 流程图展示双管线插件注册与处理流程
- `register_plugin(plugin: Plugin, target: Literal["writer", "reader"]) -> None`：向指定管线注册插件
- `register_shared_plugin(plugin: Plugin) -> None`：将同一插件实例注册到双管线
- `unregister_plugin(name: str, target: Literal["writer", "reader"]) -> None`：从指定管线注销插件
- `shutdown() -> None`：关闭所有插件和存储资源

MCS MUST NOT 持有 `MCSConfig` 实例，MUST NOT 有 `initialize()` 方法，MUST NOT 有 `persist_full()` 方法。

#### Scenario: MCS 构造不接受 Config

- **WHEN** 检查 `MCS.__init__` 的参数签名
- **THEN** MUST NOT 包含 `config: MCSConfig` 参数
- **AND** MUST 接受 `write_pipeline`, `query_engine`, `store`, `write_manager`, `read_manager` 参数

#### Scenario: ingest 调用写入管线

- **WHEN** 调用 `mcs.ingest("some text")`
- **THEN** MUST 委托给内部的 `write_pipeline.ingest()`
- **AND** 返回 `WriteContext`

#### Scenario: query 调用查询管线

- **WHEN** 调用 `mcs.query("some query")`
- **THEN** MUST 委托给内部的 `query_engine.query()`
- **AND** 返回 `List[Node]` 或后处理链的输出类型

---

### Requirement: MCS 类双 PluginManager 架构

`MCS` 类 SHALL 维护 `write_manager` 和 `read_manager` 两个 `PluginManager`。插件注册/注销 MUST 通过 `register_plugin(plugin, target)` / `unregister_plugin(name, target)` 方法指定目标管线，MUST NOT 支持隐式双注册。

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

### Requirement: 插件注册必须指定目标管线

`register_plugin()` 和 `unregister_plugin()` 方法 SHALL 接受 `target` 参数，值为 `"writer"` 或 `"reader"`。

#### Scenario: 向 writer 注册插件

- **WHEN** 调用 `mcs.register_plugin(plugin, target="writer")`
- **THEN** 插件 MUST 只注册到 `write_manager`
- **AND** `read_manager.get_by_name(plugin.get_name())` MUST 返回 `None`

#### Scenario: 向 reader 注册插件

- **WHEN** 调用 `mcs.register_plugin(plugin, target="reader")`
- **THEN** 插件 MUST 只注册到 `read_manager`
- **AND** `write_manager.get_by_name(plugin.get_name())` MUST 返回 `None`

#### Scenario: 注销插件需指定管线

- **WHEN** 调用 `mcs.unregister_plugin("alias_entry", target="reader")`
- **THEN** 只从 `read_manager` 移除插件
- **AND** 若同名插件存在于 `write_manager`，MUST NOT 受影响

---

### Requirement: 共享插件便捷注册

`register_shared_plugin()` 方法 SHALL 将同一插件实例注册到 `write_manager` 和 `read_manager` 两侧。

#### Scenario: 共享插件注册到两侧

- **WHEN** 调用 `mcs.register_shared_plugin(plugin)`
- **THEN** 插件 MUST 注册到 `write_manager`
- **AND** 插件 MUST 注册到 `read_manager`
- **AND** `write_manager.get_by_name(plugin.get_name()) is read_manager.get_by_name(plugin.get_name())` MUST 为 True

#### Scenario: 共享插件不触发跨 manager 重复检查

- **WHEN** 同一插件实例通过 `register_shared_plugin()` 注册
- **THEN** MUST NOT 抛出 ValueError（跨 manager 的同名注册是允许的）
- **AND** 若同一 manager 内已有同名插件，MUST 抛出 ValueError（单 manager 内去重）

---

### Requirement: shutdown 去重关闭共享插件

`shutdown()` 方法 SHALL 确保共享插件实例只被关闭一次。

#### Scenario: 共享插件只 shutdown 一次

- **WHEN** 插件 P 同时注册在 `write_manager` 和 `read_manager`（同一实例）
- **AND** 调用 `mcs.shutdown()`
- **THEN** P 的 `shutdown()` 方法 MUST 只被调用一次

#### Scenario: 非共享插件各关闭一次

- **WHEN** 插件 A 只在 `write_manager`，插件 B 只在 `read_manager`
- **AND** 调用 `mcs.shutdown()`
- **THEN** A 和 B 的 `shutdown()` 方法 MUST 各被调用一次

---

### Requirement: show 方法以 Markdown 流程图展示双管线

`show()` 方法 SHALL 返回 Markdown 格式字符串，包含 writer 和 reader 两条管线的处理阶段和已注册插件。

#### Scenario: show 返回 Mermaid 流程图

- **WHEN** 调用 `mcs.show()`
- **THEN** 返回的字符串 MUST 包含 Mermaid `flowchart TD` 代码块
- **AND** 包含 writer 管线的 7 个阶段
- **AND** 包含 reader 管线的 5 个阶段

#### Scenario: show 列出各管线已注册插件

- **WHEN** 调用 `mcs.show()`
- **THEN** 返回的字符串 MUST 列出 write_manager 中注册的所有插件名称和类型
- **AND** MUST 列出 read_manager 中注册的所有插件名称和类型

---

### Requirement: MCS 类位于 mcs/core/mcs.py

`MCS` 类 SHALL 定义在 `mcs/core/mcs.py`。`mcs/__init__.py` SHALL 从 `mcs.core.mcs` 导入并导出 `MCS`。

#### Scenario: 导入路径

- **WHEN** 使用 `from mcs import MCS`
- **THEN** MUST 正常工作，返回 `mcs.core.mcs.MCS` 类

#### Scenario: core 不依赖 plugins

- **WHEN** 检查 `mcs/core/mcs.py` 的非 TYPE_CHECKING 导入
- **THEN** MUST NOT 导入 `mcs/plugins/` 或 `mcs/presets/`


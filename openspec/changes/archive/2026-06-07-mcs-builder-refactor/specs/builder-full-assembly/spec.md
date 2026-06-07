## ADDED Requirements

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

#### Scenario: build 中 Store 初始化

- **WHEN** config 中包含 `sqlite_storage` 配置
- **THEN** Builder MUST 实例化 SQLiteStore 并初始化
- **AND** SQLiteStore MUST 传入 schema_extensions 和 node_extensions

#### Scenario: build 中共享插件双注册

- **WHEN** config.shared_plugins 包含插件名称
- **THEN** Builder MUST 以同一实例注册到 write_manager 和 read_manager
- **AND** `write_manager.get_by_name(name) is read_manager.get_by_name(name)` MUST 为 True

#### Scenario: build 中 load-on-startup

- **WHEN** Store 为空且 SQLiteStore 有持久化数据
- **THEN** Builder MUST 从 SQLite 加载已有数据
- **AND** MUST 重建所有 Index 插件

---

### Requirement: Builder 只依赖 core 类型

`MCSBuilder` 抽象基类的非 TYPE_CHECKING 导入 MUST 只引用 `mcs/core/` 下的模块，MUST NOT 引用 `mcs/plugins/` 或 `mcs/presets/`。

#### Scenario: Builder 无 plugins 导入

- **WHEN** 检查 `mcs/core/builder.py` 的非 TYPE_CHECKING 导入
- **THEN** MUST NOT 包含 `mcs.plugins` 或 `mcs.presets` 的导入

---

### Requirement: Builder 通过抽象方法查找插件类

`MCSBuilder` SHALL 定义抽象方法 `get_plugin_class(name: str) -> type[Plugin] | None`，由子类实现具体插件查找逻辑。

#### Scenario: 插件类查找委托给子类

- **WHEN** `MCSBuilder.build()` 处理插件列表中的每个名称
- **THEN** MUST 调用 `self.get_plugin_class(name)` 查找插件类
- **AND** 返回 `None` 的名称 MUST 被跳过

#### Scenario: 未知插件名不报错

- **WHEN** `get_plugin_class("nonexistent")` 返回 `None`
- **THEN** Builder MUST 跳过该插件名继续构建
- **AND** MUST NOT 抛出异常

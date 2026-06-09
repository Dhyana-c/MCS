## ADDED Requirements

### Requirement: MockLLMBuilder 继承 MCSBuilder

测试代码 SHALL 提供 `MockLLMBuilder` 类，继承 `MCSBuilder` 并覆写 `get_plugin_class()` 和 `_instantiate_plugin()`，使 `build()` 走父类完整流程。

#### Scenario: MockLLMBuilder 正确继承 MCSBuilder

- **WHEN** 创建 `MockLLMBuilder(config, mock_llm)` 并调用 `build()`
- **THEN** 返回的 MCS 实例 MUST 与 `MCSBuilder.build()` 流程一致
- **AND** `mock_llm` MUST 以同一实例注册到 `write_manager` 和 `read_manager`

#### Scenario: mock_llm 插件类查找

- **WHEN** `MockLLMBuilder.get_plugin_class("mock_llm")` 被调用
- **THEN** MUST 返回 `MockLLM` 类

#### Scenario: mock_llm 实例注入

- **WHEN** `MockLLMBuilder._instantiate_plugin("mock_llm")` 被调用
- **THEN** MUST 返回构造时注入的 `mock_llm` 实例（而非新建实例）
- **AND** `write_manager.get_by_name("mock_llm") is read_manager.get_by_name("mock_llm")` MUST 为 True

#### Scenario: 其他插件类查找委托给 Phase1 注册表

- **WHEN** `MockLLMBuilder.get_plugin_class("fanout_reducer")` 被调用
- **THEN** MUST 返回 Phase1 注册表中的 `FanoutReducerPlugin` 类

---

### Requirement: MockLLMBuilder 支持自定义 Store

`MockLLMBuilder` SHALL 支持通过构造函数注入外部 Store 实例，覆写 `_init_store()` 的默认行为。

#### Scenario: 注入 InMemoryStore

- **WHEN** 创建 `MockLLMBuilder(config, mock_llm, store=InMemoryStore())` 并调用 `build()`
- **THEN** 返回的 MCS 实例 MUST 使用注入的 InMemoryStore
- **AND** MUST NOT 创建新的 Store 实例

#### Scenario: 注入 SQLiteStore

- **WHEN** 创建 `MockLLMBuilder(config, mock_llm, store=SQLiteStore(config))` 并调用 `build()`
- **THEN** 返回的 MCS 实例 MUST 使用注入的 SQLiteStore
- **AND** MUST 执行 SQLiteStore 的 schema 初始化步骤

#### Scenario: 不注入 Store 时使用默认行为

- **WHEN** 创建 `MockLLMBuilder(config, mock_llm)` 不指定 store 参数
- **THEN** `_init_store()` MUST 返回 `InMemoryStore()`

---

### Requirement: 插件初始化 helper

`tests/conftest.py` SHALL 提供 `init_plugin_manager()` 函数，封装 PluginManager + PluginContext 初始化模式。

#### Scenario: 基本初始化

- **WHEN** 调用 `init_plugin_manager(store, plugin, extra_plugins=[mock_llm])`
- **THEN** MUST 创建 PluginManager，注册 extra_plugins 和 plugin
- **AND** MUST 构建 PluginContext 并调用 `pm.initialize_all(ctx)`
- **AND** MUST 返回 plugin 实例

#### Scenario: 默认 config

- **WHEN** 调用 `init_plugin_manager(store, plugin)` 不指定 config
- **THEN** PluginContext 的 config MUST 默认为 `MCSConfig()`

#### Scenario: 自定义 config

- **WHEN** 调用 `init_plugin_manager(store, plugin, config=custom_config)`
- **THEN** PluginContext 的 config MUST 使用 `custom_config`

---

### Requirement: FanoutReducer fixture

`tests/conftest.py` SHALL 提供 `fanout_reducer` fixture，封装 FanoutReducerPlugin 的初始化模式。

#### Scenario: fixture 返回已初始化的 FanoutReducerPlugin

- **WHEN** 测试使用 `fanout_reducer` fixture
- **THEN** MUST 返回已初始化的 `FanoutReducerPlugin` 实例
- **AND** 该实例 MUST 已通过 `pm.initialize_all()` 初始化

#### Scenario: fixture 使用默认参数

- **WHEN** 使用 `fanout_reducer` fixture
- **THEN** FanoutReducerPlugin MUST 使用 `{"floor": 16}` 配置

---

### Requirement: 测试文件删除重复构建函数

以下测试文件 SHALL 删除手动组装 MCS/QueryEngine/WritePipeline 的函数，改用 conftest 提供的构建工厂和 helper：

- `test_pipeline_write.py`：删除 `_build_mcs_with_store`
- `test_pipeline_query.py`：删除 `_build_engine`
- `test_mcs_api.py`：删除 `_build_mcs`
- `test_hub_fallback.py`：删除 `_init`
- `test_directed_navigation.py`：删除 `_init_plugin`
- `test_directed_hierarchy.py`：删除 `_fanout_with_root`
- `test_seed_graph.py`：删除 `_fanout_with_root`

#### Scenario: 测试使用 conftest 构建工厂

- **WHEN** 测试需要构建 MCS 实例
- **THEN** MUST 使用 `MockLLMBuilder` 或 `mcs_with_mock_llm` fixture
- **AND** MUST NOT 包含手动组装 Store → PluginManager → 插件注册 → 初始化 → 管线构建的代码

#### Scenario: 测试使用插件初始化 helper

- **WHEN** 测试需要初始化单个插件
- **THEN** MUST 使用 `init_plugin_manager()` helper
- **AND** MUST NOT 包含手动创建 PluginManager + PluginContext 的代码

#### Scenario: 重构后所有测试通过

- **WHEN** 运行 `pytest tests/`
- **THEN** 所有测试 MUST 通过，无回归

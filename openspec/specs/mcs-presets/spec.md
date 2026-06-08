# mcs-presets Specification

## Purpose
TBD - created by archiving change mcs-builder-abstraction. Update Purpose after archive.

## Requirements

### Requirement: presets 模块提供 Phase1 默认构建器

`mcs/presets/phase1.py` SHALL 提供 `Phase1Builder` 类，继承 `MCSBuilder`，实现 Phase1 插件注册表查找，并按 shared/write/read 分类分配默认插件。插件注册表的 import 路径 SHALL 从 `mcs.plugins.phase1.<plugin>` 更新为 `mcs.plugins.<type>.<plugin>`。

#### Scenario: Phase1Builder 查找插件类

- **WHEN** 调用 `Phase1Builder(config).get_plugin_class("alias_index")`
- **THEN** MUST 返回 `AliasIndexPlugin` 类
- **AND** 内部 import 路径 MUST 为 `from mcs.plugins.index.alias_index import AliasIndexPlugin`

#### Scenario: Phase1Builder 构建完整实例

- **WHEN** 调用 `Phase1Builder(config).build()`
- **THEN** MUST 返回已完成 `initialize()` 的 MCS 实例，包含双 PluginManager

#### Scenario: 无 phase1 import 路径

- **WHEN** 检查 `mcs/presets/phase1.py` 中所有 import 语句
- **THEN** MUST NOT 存在 `from mcs.plugins.phase1` 形式的导入

---

### Requirement: presets 模块提供快捷工厂函数

`mcs/presets/phase1.py` SHALL 提供 `create_mcs()` 函数，接受 `write_llm`、`read_llm`、`db_path`、`token_budget` 等参数，返回已初始化的 MCS 实例。

#### Scenario: 一键创建 MCS（读写同模型）

- **WHEN** 调用 `create_mcs(llm="deepseek", db_path="test.db")`
- **THEN** MUST 返回已初始化的 MCS 实例
- **AND** `write_llm` 和 `read_llm` MUST 都指向 `deepseek_llm`

#### Scenario: 一键创建 MCS（读写不同模型）

- **WHEN** 调用 `create_mcs(write_llm="ollama", read_llm="deepseek", db_path="test.db")`
- **THEN** MUST 返回已初始化的 MCS 实例
- **AND** `mcs.write_llm.get_name()` MUST 返回 `"ollama_llm"`
- **AND** `mcs.read_llm.get_name()` MUST 返回 `"deepseek_llm"`

#### Scenario: 快捷工厂配置覆盖

- **WHEN** 调用 `create_mcs(token_budget=16000)`
- **THEN** 返回的 MCS 实例 MUST 使用 16000 作为 token_budget

---

### Requirement: presets 模块提供插件注册表函数

`mcs/presets/phase1.py` SHALL 提供 `get_phase1_plugin_registry() -> dict[str, type[Plugin]]` 函数，返回 Phase1 全部插件类映射。所有插件的 import 路径 SHALL 使用新的类型目录结构。

#### Scenario: 注册表完整性

- **WHEN** 调用 `get_phase1_plugin_registry()`
- **THEN** 返回的字典 MUST 包含以下插件类：
  - `sqlite_storage`, `source_tracking`, `summary`（shared）
  - `idempotency_check`, `fanout_reducer`, `summary_regen`（write）
  - `alias_index`, `alias_entry`, `hub_fallback`, `priority_trim`（read）
  - `deepseek_llm`, `claude_llm`, `ollama_llm`（LLM）

#### Scenario: 注册表 import 路径正确

- **WHEN** 检查 `get_phase1_plugin_registry()` 函数内部
- **THEN** 所有插件 import MUST 使用 `from mcs.plugins.<type>.<plugin_name>` 格式
- **AND** MUST NOT 使用 `from mcs.plugins.phase1.<plugin_name>` 格式

---

### Requirement: Phase1 默认插件分配

`MCSConfig.knowledge_graph()` SHALL 按 shared/write/read 分类返回默认插件列表。

#### Scenario: shared_plugins 默认值

- **WHEN** 调用 `MCSConfig.knowledge_graph()`
- **THEN** `config.shared_plugins` MUST 包含 `["sqlite_storage", "source_tracking", "summary"]`

#### Scenario: write_plugins 默认值

- **WHEN** 调用 `MCSConfig.knowledge_graph()`
- **THEN** `config.write_plugins` MUST 包含 `["idempotency_check", "fanout_reducer", "summary_regen"]`

#### Scenario: read_plugins 默认值

- **WHEN** 调用 `MCSConfig.knowledge_graph()`
- **THEN** `config.read_plugins` MUST 包含 `["alias_index", "alias_entry", "hub_fallback", "priority_trim"]`

#### Scenario: LLM 参数映射

- **WHEN** 调用 `MCSConfig.knowledge_graph(write_llm="ollama", read_llm="deepseek")`
- **THEN** `config.write_llm` MUST 为 `"ollama_llm"`
- **AND** `config.read_llm` MUST 为 `"deepseek_llm"`

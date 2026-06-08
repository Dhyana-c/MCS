## MODIFIED Requirements

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

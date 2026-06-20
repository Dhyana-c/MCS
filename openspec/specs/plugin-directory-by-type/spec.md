## Purpose
规定插件目录按 PluginType 枚举值分组（entry/trim/postprocess/llm/ 等），import 路径反映类型，消除 phase1/phase2 分期目录。

## Requirements

### Requirement: 插件目录按 PluginType 分组

插件目录结构 SHALL 按 `PluginType` 枚举值分组，每个类型对应 `mcs/plugins/<type>/` 子目录。开发者 SHALL 能从目录名直接判断插件的类型职责。

#### Scenario: 目录结构与 PluginType 一致

- **WHEN** 列出 `mcs/plugins/` 目录
- **THEN** 子目录名 MUST 与 `PluginType` 枚举值对应（小写）：`entry/`、`trim/`、`postprocess/`、`preprocess/`、`maintenance/`、`index/`、`llm/`、`seed_selector/`

#### Scenario: 插件文件位于对应类型目录

- **WHEN** 查找 `alias_entry` 插件文件
- **THEN** 文件 MUST 位于 `mcs/plugins/entry/alias_entry.py`

#### Scenario: 多类型插件标注所有类型

- **WHEN** 一个插件实现多个 `PluginType`（如 `source_tracking` 同时实现 PREPROCESS、NODE_EXTENSION、STORAGE_SCHEMA_EXT）
- **THEN** 插件文件 MUST 位于其主要类型目录
- **AND** 插件类文档字符串 MUST 明确标注所有实现的类型

---

### Requirement: 插件 import 路径反映类型

插件 import 路径 SHALL 包含类型目录名，形如 `from mcs.plugins.<type>.<plugin_name> import ...`。

#### Scenario: import 路径格式正确

- **WHEN** 导入 `AliasEntryPlugin`
- **THEN** import 语句 MUST 为 `from mcs.plugins.entry.alias_entry import AliasEntryPlugin`

#### Scenario: 无 phase1/phase2 路径

- **WHEN** 检查项目中所有 Python 文件的 import 语句
- **THEN** MUST NOT 存在 `from mcs.plugins.phase1` 或 `from mcs.plugins.phase2`

---

### Requirement: 删除 phase1/phase2 目录

旧的 `mcs/plugins/phase1/` 和 `mcs/plugins/phase2/` 目录 SHALL 被删除，不再保留空壳或 deprecated alias。

#### Scenario: phase 目录不存在

- **WHEN** 检查 `mcs/plugins/` 目录
- **THEN** MUST NOT 存在 `phase1` 或 `phase2` 子目录

#### Scenario: 无残留 __pycache__

- **WHEN** 检查 `mcs/plugins/` 目录树
- **THEN** MUST NOT 存在 `phase1/__pycache__` 或 `phase2/__pycache__`

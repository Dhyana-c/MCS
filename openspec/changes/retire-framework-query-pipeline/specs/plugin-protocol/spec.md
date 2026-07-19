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

### Requirement: MCSBuilder 抽象基类定义构建契约

`PluginType` 枚举 SHALL 移除 `ARBITRATION` / `POSTPROCESS` / `QUERY_PREPROCESS` 三个值。`PluginManager` SHALL 移除"ArbitrationPlugin 单例强制"逻辑（原注册第二个 ArbitrationPlugin 报 `ConfigurationError` 的检查删除）。其余 PluginType 与单例 / 排序规则不变。

#### Scenario: PluginType 不含已退役枚举值

- **WHEN** 检查 `PluginType` 枚举成员
- **THEN** MUST NOT 含 `ARBITRATION` / `POSTPROCESS` / `QUERY_PREPROCESS`；其余（ENTRY / TRIM / WRITE_PREPROCESS / INDEX / LLM / NODE_EXTENSION / EDGE_EXTENSION / STORAGE_SCHEMA_EXT / COMPACTION / MAINTENANCE）MUST 保留

#### Scenario: ArbitrationPlugin 单例检查移除

- **WHEN** 向 `PluginManager` 注册插件
- **THEN** MUST NOT 触发"只能注册一个 ArbitrationPlugin"的 `ConfigurationError`（该检查随类型删除）

> 其余正文 impl 期核定。

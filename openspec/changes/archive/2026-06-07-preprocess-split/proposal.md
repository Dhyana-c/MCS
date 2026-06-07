# Proposal: preprocess-split — 前置处理插件拆分

| 字段     | 值                                                  |
|----------|-----------------------------------------------------|
| 状态     | draft                                               |
| 影响范围 | plugin.py, preprocess_plugin.py, query_engine.py, write_pipeline.py, source_tracking.py, tests/ |

## 问题

当前 `PluginType.PREPROCESS` 被写入管线和查询管线**共用**，但两者的前置处理语义完全不同：

| 维度           | Write Pipeline Stage ①              | Query Pipeline Stage ①              |
|----------------|--------------------------------------|--------------------------------------|
| **职责**       | 文本准备：幂等检查、摘要生成、去重   | 查询增强：改写、同义词扩展、意图识别 |
| **Context**    | `WriteContext`（含 metadata / skip） | `QueryContext`（含 seed / budget）   |
| **短路**       | `ctx.skip = True` → 终止整个 ingest | 无短路概念                          |
| **现有插件**   | `IdempotencyCheckPlugin`（仅写有意义）| 无专用插件                          |

共用导致的问题：

1. **类型安全丧失** — `preprocess(text, ctx: Any)` 无法区分 `WriteContext` vs `QueryContext`
2. **组合不可控** — 注册一个写管线前置插件会同时影响查询管线（反之亦然）
3. **短路语义不对称** — 写管线支持 `skip`，查询管线不支持，一个接口承载两种控制流
4. **违反既有模式** — `POSTPROCESS`（查询专用）、`COMPACTION`（写入专用）、`ENTRY/TRIM`（查询专用）都是单侧类型，`PREPROCESS` 是唯一"双栖"类型

## 方案

将 `PluginType.PREPROCESS` 拆分为：

- `PluginType.WRITE_PREPROCESS` — 写入管线 Stage ①
- `PluginType.QUERY_PREPROCESS` — 查询管线 Stage ①

对应的接口：

- `WritePreprocessPluginInterface` — `preprocess(text, ctx: WriteContext) -> str`
- `QueryPreprocessPluginInterface` — `preprocess(text, ctx: QueryContext) -> str`

保留 `PREPROCESS` 作为**废弃别名**（`PREPROCESS = WRITE_PREPROCESS`），一个版本后移除。

多接口插件可同时实现两个接口，通过 `get_types()` 返回 `{WRITE_PREPROCESS, QUERY_PREPROCESS}`。

## 不做

- 不改变 `PostprocessPluginInterface`（已是查询专用，无歧义）
- 不改变 `PluginManager` 的索引机制（`get_types()` 已支持多类型）
- 不改变 `execute()` 统一入口模式

## 迁移影响

| 文件                                  | 变更                                                     |
|---------------------------------------|----------------------------------------------------------|
| `mcs/core/plugin.py`                  | 新增 `WRITE_PREPROCESS`、`QUERY_PREPROCESS`；`PREPROCESS` → 废弃别名 |
| `mcs/interfaces/preprocess_plugin.py` | 拆为 `write_preprocess_plugin.py` + `query_preprocess_plugin.py` |
| `mcs/interfaces/__init__.py`          | 导出新接口                                               |
| `mcs/core/write_pipeline.py`          | `_run_preprocess` 改用 `WRITE_PREPROCESS`；`_mark_ingested_if_success` 同步 |
| `mcs/core/query_engine.py`            | `_run_preprocess` 改用 `QUERY_PREPROCESS`               |
| `mcs/plugins/phase1/source_tracking.py`| `IdempotencyCheckPlugin` → 继承 `WritePreprocessPluginInterface` |
| `tests/test_pipeline_write.py`        | 更新导入和类型                                           |
| `tests/test_pipeline_query.py`        | 更新导入和类型                                           |
| `tests/test_plugin_chains.py`         | 更新导入和类型                                           |

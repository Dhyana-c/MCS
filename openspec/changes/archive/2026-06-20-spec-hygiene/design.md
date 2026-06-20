# Design: spec-hygiene

## 决策

1. **格式修正 ≠ 需求变更**：6 个单 delta 头 spec 的 requirement 内容不变，仅修头使其可解析。`auto-persistence` 的 `## MODIFIED Requirements` 段是错置重复——其 2 条需求（写流程 6→7 段、WriteContext 7→8 字段）本属 write-pipeline 能力，且 write-pipeline 主 spec 现已有 7 段 / 8 字段正本（已核实），删除无信息损失。
2. **project-skeleton 走 delta**：其内容是真需求变更（目录 / 接口 / MCS 方法与现码不符），用 MODIFIED / REMOVED / ADDED 增量同步。
3. **README_v2 删除而非修复**：与 `README.md` 高度重复且全篇过时（旧模型、断链、错误插件数），修复后仍冗余。

## 已核实的现码事实（delta 依据）

- `mcs/` 顶层：`core/` `diagnostics/` `entities/` `interfaces/` `plugins/` `presets/` `prompts/` `utils/` `stores/` + `rendering.py`
- `mcs/plugins/` 按类型：`entry/` `index/` `llm/` `maintenance/` `postprocess/` `preprocess/` `trim/`（**无** phase1/phase2）
- `mcs/interfaces/`：16 个接口文件，按 PluginType + 扩展接口组织（**无** pipeline_hook.py / query_hook.py）
- `mcs.core.mcs.MCS`：瘦门面，方法 `ingest/query/run_maintenance/register_plugin/register_shared_plugin/unregister_plugin/get_plugin/show/shutdown`（**无** initialize / persist_full）
- `docs/`：12 个文件（含 INDEX/getting-started/architecture/graph-model-design/plugin-system/api-reference/configuration/mcp-server/memory-agent/evaluation/faq/known-issues；**无** core-flows/technical-design/memory-agent-design）

## 风险

- project-skeleton 可能仍有本次未覆盖的过时点（如"业务逻辑零实现"等脚手架期需求）——本次只修已核实矛盾，更深审计留后续 change。

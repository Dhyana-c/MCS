## Why

`unified-workflow-architecture` change 定义了 MCS 的新工作流架构（4 个 capability：query-pipeline / write-pipeline / plugin-protocol / llm-interaction），但实际代码仍按旧 9+7 状态点 hook 模型组织。本 change 在新架构基础上实施 Phase 1（知识图谱模式），包括：接口层全面重写、核心引擎按新流程改造、Phase 1 五个默认插件落地、测试覆盖、可用的最小端到端示例。

完成本 change 后，MCS 可用于真实的"可扩展记忆系统"场景：调用方传入文本得到节点变更，传入 query 得到 `List[Node]` 记忆。

## What Changes

- **接口层（5 新 + 2 删 + 1 改）**
  - 新增 `mcs/interfaces/entry_plugin.py`、`trim_plugin.py`、`arbitration_plugin.py`、`postprocess_plugin.py`、`compaction_plugin.py`
  - 删除 `mcs/interfaces/pipeline_hook.py`、`mcs/interfaces/query_hook.py`
  - 重写 `mcs/interfaces/llm.py`：从 7 个语义方法改为统一 `call(purpose, nodes_in, free_args)`；新增 `system_prompt` / `user_template` / `parser` 注册点
  - 扩展 `mcs/interfaces/node_extension.py`：新增可选 `render(node, purpose) -> str | None` 方法
- **核心引擎**
  - `mcs/core/serializer.py` → `mcs/core/context_renderer.py`（按 purpose 渲染 + 聚合 NodeExtension 贡献）
  - 重写 `mcs/core/write_pipeline.py`：6 段管线 + `WriteContext`（7 字段）+ `DecisionList` 数据结构
  - 重写 `mcs/core/query_engine.py`：5 段管线 + `QueryContext`（4 字段）+ 默认返回 `List[Node]`
  - 升级 `mcs/core/plugin_manager.py`：支持 5 新插件接口的优先级排序、exclusive 短路、单例约束
- **Phase 1 默认插件（5 个）**
  - `AliasEntryPlugin`（priority=100，实现 EntryPluginInterface + NodeExtension(aliases)）
  - `HubFallbackEntryPlugin`（priority=0，新增）
  - `PriorityTrimPlugin`（默认 TrimPlugin 实现）
  - `SummaryPlugin`（NodeExtension + render 贡献 summary 字段）
  - `SourceTrackingPlugin`（NodeExtension + render 贡献 sources 字段 + 写前置 PostprocessPlugin 做幂等）
  - `SQLiteStoragePlugin`（基础持久化，不变）
  - `DeepSeekLLMPlugin`（厂商适配，纯 `call(system, user) -> str`，不含 prompt 模板）
- **Prompt 模板与解析器**
  - `mcs/prompts/` 下为 9 个 purpose 各提供 default `system_prompt` / `user_template` / `parser`
- **测试**
  - 接口冒烟测试（新 5 接口可被实例化错误捕获）
  - 单元测试：QueryContext / WriteContext / DecisionList / ContextRenderer 字段贡献
  - 集成测试：mock LLM 完整跑通 ingest → query 的 5+6 段流程
  - 默认插件集行为测试（优先级、exclusive、链式串联）
- **文档**
  - 更新 `examples/` 增加可运行示例（mock LLM 模式）
  - 更新 README 安装与运行说明

## Capabilities

### New Capabilities
- `phase1-defaults`: 定义 Phase 1（知识图谱模式）的具体选型：默认插件集 5 个、各自优先级、9 个 purpose 的默认 prompt 模板就位、默认 token_budget、错误处理基线。这些是 `unified-workflow-architecture` 抽象契约的具体填充。

### Modified Capabilities
（无 —— 本 change 不修改 query-pipeline / write-pipeline / plugin-protocol / llm-interaction 这 4 个 capability 的契约；仅在新 capability `phase1-defaults` 下规定 Phase 1 的具体选择）

## Impact

- **代码层（全部在本 change 内执行）**
  - 新增文件：5 个 interface + 1 个 `context_renderer.py` + `HubFallbackEntryPlugin` + 9 个 prompt 模板组（system/template/parser）
  - 重写文件：`llm.py`、`write_pipeline.py`、`query_engine.py`、`plugin_manager.py`、`alias_index.py`、`source_tracking.py`、`summary.py`、`deepseek_llm.py`、`sqlite_storage.py`
  - 删除文件：`pipeline_hook.py`、`query_hook.py`、`serializer.py`（被 `context_renderer.py` 取代）
- **测试层**
  - 新增 `tests/test_pipeline_query.py`、`tests/test_pipeline_write.py`、`tests/test_context_renderer.py`、`tests/test_plugin_chains.py`
  - 现有 `tests/test_skeleton.py` 需更新（接口清单变化）
- **文档层**
  - `examples/basic_usage.py` 实现
  - `examples/wiki_example.py` 实现
  - `README.md` 安装/运行说明更新
- **配置层**
  - `mcs/core/config.py` 的 `MCSConfig.knowledge_graph()` 工厂方法更新默认插件清单
- **依赖关系**：本 change 依赖 `unified-workflow-architecture` 已归档（4 个 capability spec 已落地到 `openspec/specs/`）。
- **不影响**：
  - `MCS技术方案.md`、`测试方案.md`（底层机制不变）
  - `openspec/specs/project-skeleton/spec.md`（目录契约不变，仅文件内容大改）
  - 已归档的 `2026-05-28-init-project-skeleton`

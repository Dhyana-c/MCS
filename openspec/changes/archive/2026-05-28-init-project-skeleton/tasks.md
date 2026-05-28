## 1. 包管理与工具配置

- [x] 1.1 创建 `pyproject.toml`（含 `[project]` 元数据、`requires-python = ">=3.10"`、运行时依赖 `openai>=1.0,<2.0` 与 `jieba`、开发依赖 `pytest` 和 `pytest-asyncio` 和 `ruff`）
- [x] 1.2 在 `pyproject.toml` 中添加 `[tool.setuptools.packages.find]` 配置，`include = ["mcs*"]`，避免误打包根目录 markdown 文件
- [x] 1.3 在 `pyproject.toml` 中添加 `[tool.pytest.ini_options]`，配置 `testpaths = ["tests"]`
- [x] 1.4 在 `pyproject.toml` 中添加 `[tool.ruff]`，配置 `line-length = 100`、`target-version = "py310"`、基础 lint 规则
- [x] 1.5 创建 `.gitignore`（含 `__pycache__/`、`*.pyc`、`.venv/`、`*.egg-info/`、`*.db`、`.pytest_cache/`、`.ruff_cache/`、`.idea/`、`.vscode/`）

## 2. 目录结构

- [x] 2.1 创建 `mcs/` 包目录及所有子目录：`mcs/core/`, `mcs/interfaces/`, `mcs/plugins/`, `mcs/plugins/phase1/`, `mcs/plugins/phase2/`, `mcs/prompts/`, `mcs/utils/`
- [x] 2.2 创建 `tests/` 和 `examples/` 目录（与 `mcs/` 同级）
- [x] 2.3 为 `mcs/` 及所有子目录添加空的 `__init__.py`（共 7 个 `__init__.py`）

## 3. 接口层（8 个 ABC 文件）

- [x] 3.1 `mcs/interfaces/storage.py`：定义 `StorageInterface`（`initialize / save / load / save_node / save_edge` 5 个 `@abstractmethod`，方法体 `pass`）— **注**：`initialize` 签名改为 `(context: PluginContext)`，与 `Plugin.initialize` 对齐避免多继承冲突，见文件 docstring
- [x] 3.2 `mcs/interfaces/index.py`：定义 `IndexInterface`（`build / lookup / add_entry / remove_entry / update_entry` 5 个抽象方法）
- [x] 3.3 `mcs/interfaces/llm.py`：定义 `LLMInterface`（`call / extract_concepts / check_exists / decide_hub / decide_directions / synthesize / generate_aliases / generate_summary` 8 个抽象方法）
- [x] 3.4 `mcs/interfaces/node_extension.py`：定义 `NodeExtensionInterface`（`schema / default / serialize / deserialize` 4 个抽象方法）— **注**：`name` 改为类属性继承自 `Plugin`，避免与抽象方法重名冲突，见文件 docstring
- [x] 3.5 `mcs/interfaces/pipeline_hook.py`：定义 `PipelineHookInterface`，含 9 个 `on_<state>` 方法（`on_ingest_start` ~ `on_ingest_end`），每个方法体为 `pass`（默认空实现，非 abstractmethod）
- [x] 3.6 `mcs/interfaces/query_hook.py`：定义 `QueryHookInterface`，含 7 个 `on_<state>` 方法（`on_query_start` ~ `on_query_end`），每个方法体为 `pass`
- [x] 3.7 `mcs/interfaces/storage_schema_ext.py`：定义 `StorageSchemaExtensionInterface`（`node_columns / auxiliary_tables` 2 个抽象方法）— **注**：同 3.4，`name` 改为类属性继承自 `Plugin`
- [x] 3.8 `mcs/interfaces/maintenance.py`：定义 `MaintenanceInterface`（`run / should_run` 2 个抽象方法）

## 4. 核心引擎 - 数据结构

- [x] 4.1 `mcs/core/graph.py`：定义 `Node` dataclass（`id, name, content, role, extensions: dict[str, Any]`）和 `Edge` dataclass（`source_id, target_id, direction`）；定义 `GraphStore` 类，11 个方法体均 `raise NotImplementedError("Phase 1 implementation pending")`
- [x] 4.2 `mcs/core/token_budget.py`：定义 `TokenBudget` 类（`__init__(max_tokens)`、`estimate / check_subgraph / get_budget_for_merge`，方法体 NotImplementedError）
- [x] 4.3 `mcs/core/serializer.py`：定义 `Serializer` 类，`serialize()` 方法 NotImplementedError；`get_summary(node)` **必须实现**（读 `node.extensions["summary"]["text"]` fallback 到 `content[:200]`），保证 SummaryPlugin 未启用时 graceful degrade

## 5. 核心引擎 - 处理流水线

- [x] 5.1 `mcs/core/write_pipeline.py`：定义 `WritePipelineState` Enum（9 个值）；定义 `HookContext` dataclass（含 `text / concepts / concept / anchors / exists / existing_node / node / skip / metadata` 字段）；定义 `WritePipeline` 类（`__init__ / _emit / ingest / place / merge_community / reduce_fanout / _find_anchors` 方法，方法体 NotImplementedError 或基础 emit 框架）
- [x] 5.2 `mcs/core/query_engine.py`：定义 `QueryPipelineState` Enum（7 个值）；定义 `QueryContext` dataclass（含 `query / seeds / current_node / accumulated / answer / metadata` 字段）；定义 `QueryEngine` 类（`__init__ / _emit / query / _locate_seeds / _traverse / _synthesize` 方法，方法体 NotImplementedError）

## 6. 核心引擎 - 插件管理与配置

- [x] 6.1 `mcs/core/config.py`：定义 `MCSConfig` dataclass，含工厂方法 `knowledge_graph()` 和 `memory_system()`，分别返回正确的 5 / 11 个插件名称列表（按 architecture.md §5.1）
- [x] 6.2 `mcs/core/plugin_manager.py`：定义 `PluginContext` dataclass（含 `graph / config / token_budget / serializer / plugin_manager` 字段）；定义 `PluginManager` 类（`register / get / get_all / collect_schema_extensions / initialize_all / shutdown_all`，基础容器实现可正常工作，无 NotImplementedError）
- [x] 6.3 `mcs/plugins/__init__.py` 添加 `base.py`：定义 `Plugin` ABC 基类（`name / version / interfaces` 类属性占位，`__init__ / initialize / shutdown` 方法）

## 7. Phase 1 插件占位（5 个）

- [x] 7.1 `mcs/plugins/phase1/alias_index.py`：定义 `AliasIndexPlugin(Plugin, IndexInterface, NodeExtensionInterface, PipelineHookInterface)`，所有接口方法体 NotImplementedError；`name = "alias_index"`
- [x] 7.2 `mcs/plugins/phase1/summary.py`：定义 `SummaryPlugin(Plugin, NodeExtensionInterface, PipelineHookInterface)`；`name = "summary"`
- [x] 7.3 `mcs/plugins/phase1/source_tracking.py`：定义 `Source` dataclass（`doc_id, chunk_id, content_hash, section_title=None`）；定义 `SourceTrackingPlugin(Plugin, NodeExtensionInterface, PipelineHookInterface, StorageSchemaExtensionInterface)`，含 `update_document / purge_orphans` 公共 API 方法骨架；`name = "source_tracking"`
- [x] 7.4 `mcs/plugins/phase1/sqlite_storage.py`：定义 `SQLiteStoragePlugin(Plugin, StorageInterface)`，含 `_create_tables` 方法骨架；`name = "sqlite_storage"`
- [x] 7.5 `mcs/plugins/phase1/deepseek_llm.py`：定义 `DeepSeekLLMPlugin(Plugin, LLMInterface)`，所有 LLM 方法体 NotImplementedError；`name = "deepseek_llm"`

## 8. Phase 2 插件预留（仅 docstring，无类定义）

- [x] 8.1 `mcs/plugins/phase2/event_layer.py`：仅含模块 docstring："EventLayerPlugin - Phase 2，本期不实现。见 architecture.md §7。"
- [x] 8.2 `mcs/plugins/phase2/versioning.py`：仅含模块 docstring
- [x] 8.3 `mcs/plugins/phase2/confidence.py`：仅含模块 docstring
- [x] 8.4 `mcs/plugins/phase2/timeseries_entry.py`：仅含模块 docstring
- [x] 8.5 `mcs/plugins/phase2/gc.py`：仅含模块 docstring
- [x] 8.6 `mcs/plugins/phase2/arbitration.py`：仅含模块 docstring

## 9. Prompt 模板占位（7 个）

- [x] 9.1 `mcs/prompts/extract.py`：定义 `EXTRACT_CONCEPTS` 常量为占位字符串 `""""""`
- [x] 9.2 `mcs/prompts/place.py`：定义 `CHECK_EXISTS` 占位
- [x] 9.3 `mcs/prompts/merge.py`：定义 `DECIDE_HUB` 占位
- [x] 9.4 `mcs/prompts/traverse.py`：定义 `DECIDE_DIRECTIONS` 占位
- [x] 9.5 `mcs/prompts/synthesize.py`：定义 `SYNTHESIZE` 占位
- [x] 9.6 `mcs/prompts/aliases.py`：定义 `GENERATE_ALIASES` 占位
- [x] 9.7 `mcs/prompts/summary.py`：定义 `GENERATE_SUMMARY` 占位

## 10. Utils 占位

- [x] 10.1 `mcs/utils/tokenizer.py`：定义 `ChineseTokenizer` 类骨架（`__init__ / tokenize`，方法体 NotImplementedError）
- [x] 10.2 `mcs/utils/text_utils.py`：空文件 + docstring

## 11. 测试框架

- [x] 11.1 `tests/conftest.py`：空文件 + docstring，预留 fixtures 挂载位
- [x] 11.2 `tests/test_skeleton.py`：smoke test，验证 (a) 所有 `mcs.*` 子包可被导入、(b) 所有 ABC 接口直接实例化时抛 TypeError、(c) `Source` 在 `mcs.plugins.phase1.source_tracking` 但**不**在 `mcs.core.graph`、(d) 5 个 Phase 1 插件类的 `name` 类属性与文件名一致

## 12. 文档

- [x] 12.1 更新 `README.md`：项目简介（1-2 段）、引用 `MCS技术方案.md` 和 `openspec/specs/architecture.md`、安装命令 `pip install -e .`、测试命令 `pytest`、Phase 1 开发路线引用 `openspec/changes/phase1-knowledge-graph/`
- [x] 12.2 创建 `examples/README.md`：说明"Phase 1 实现完成后补充示例代码"

## 13. 验收

- [x] 13.1 在干净 venv 执行 `pip install -e .`，命令成功完成（Python 3.13.5，所有运行时和开发依赖装好）
- [x] 13.2 执行 `pytest`，53 个用例全过（含模块导入、ABC 行为、Source 位置、插件 name、状态机大小、Node 字段集、默认插件清单、get_summary fallback）
- [x] 13.3 执行 `ruff check .`，零 lint 错误（73 → 18 → 0；hook 接口去掉 ABC 继承解决 B024/B027）
- [x] 13.4 `python -c "import mcs; import mcs.core.graph; import mcs.interfaces.llm; import mcs.plugins.phase1.alias_index"` 成功
- [x] 13.5 在 OpenSpec 中标记本 change 为 done：`openspec status --change init-project-skeleton` 确认 isComplete = true

## Why

架构设计（`architecture.md` v2.0）和 Phase 1 规划（`phase1-knowledge-graph/proposal.md`）已完成对齐，定义了核心引擎 + 接口层 + 插件层的模块划分。现在需要把抽象的架构落地为可工作的 Python 项目骨架——目录结构、占位模块、包管理、测试框架——为后续 `phase1-knowledge-graph` 的实现填充提供基础。本 change 不实现任何业务逻辑。

## What Changes

- 按 `architecture.md` §8 创建完整目录结构：`mcs/core/`, `mcs/interfaces/`, `mcs/plugins/phase1/`, `mcs/plugins/phase2/`（预留）, `mcs/prompts/`, `mcs/utils/`, `examples/`, `tests/`
- 创建所有核心模块的占位文件：
  - 接口层（7 个 ABC）：`StorageInterface`, `IndexInterface`, `LLMInterface`, `NodeExtensionInterface`, `PipelineHookInterface`, `QueryHookInterface`, `StorageSchemaExtensionInterface`, `MaintenanceInterface`
  - 核心引擎（7 个模块）：`graph.py` (Node/Edge/GraphStore), `token_budget.py`, `serializer.py`, `write_pipeline.py` (含 WritePipelineState/HookContext), `query_engine.py` (含 QueryPipelineState/QueryContext), `plugin_manager.py`, `config.py`
  - Phase 1 插件 5 个占位：`alias_index.py`, `summary.py`, `source_tracking.py` (含 Source 数据类), `sqlite_storage.py`, `deepseek_llm.py`
  - Phase 2 插件 6 个空占位文件（仅 `__init__.py` + 注释说明）
  - Prompt 模板 7 个占位：`extract.py`, `place.py`, `merge.py`, `traverse.py`, `synthesize.py`, `aliases.py`, `summary.py`
- 添加 `pyproject.toml`：包元数据、Python 3.10+ 约束、运行时依赖（openai, jieba）、开发依赖（pytest, ruff）
- 配置 pytest 测试框架：`pyproject.toml` 内 `[tool.pytest.ini_options]` + `tests/conftest.py` 占位
- 配置代码风格工具：`ruff` 配置（line-length, target-version, lint rules）
- 添加 `.gitignore`：Python / venv / IDE / SQLite db 标准排除项
- 更新 `README.md`：项目简介、架构概览引用、安装说明、Phase 1 开发路线引用
- **不实现任何业务逻辑**：所有方法体使用 `pass` 或 `raise NotImplementedError("Phase 1 implementation pending")`

## Capabilities

### New Capabilities
- `project-skeleton`: 定义项目目录结构、模块组织规范、Python 包配置、测试框架集成的硬性约束。后续所有实现 change 必须遵守此结构。

### Modified Capabilities
（无 —— 这是初始化 change，不修改任何已有 capability）

## Impact

- **新建目录**：`mcs/`（含 5 个子包）、`tests/`、`examples/`
- **新建文件**：约 30 个 Python 占位文件、`pyproject.toml`、`.gitignore`、`tests/conftest.py`
- **更新文件**：`README.md`
- **不影响**：`architecture.md`、`phase1-knowledge-graph/proposal.md`、已有 `.claude/` 配置
- **依赖关系**：
  - 本 change 完成后，`phase1-knowledge-graph` change 才能开始 apply
  - 本 change 不依赖任何已有 change
- **运行时依赖引入**：`openai` (DeepSeek 兼容 OpenAI 接口)、`jieba` (中文分词)
- **开发依赖引入**：`pytest`、`pytest-asyncio`、`ruff`

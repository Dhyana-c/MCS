# project-skeleton Specification

## Purpose
定义项目目录结构与接口层完整性，包括 mcs 包（core/interfaces/plugins/presets/prompts/utils）、tests 和 examples 目录布局，以及所有架构接口的 ABC 类。
## Requirements
### Requirement: 项目目录结构

The system SHALL maintain the directory structure defined in `architecture.md` §8, including the `docs/` directory for conceptual / reference documents, plugins organized by PluginType, and root-level open source files.

#### Scenario: 根目录存在 mcs 包

- **WHEN** 项目初始化完成
- **THEN** 根目录下存在 `mcs/` 目录，包含子目录 `entities/`, `core/`, `interfaces/`, `plugins/`, `presets/`, `prompts/`, `utils/`, `stores/`, `diagnostics/`，以及顶层模块 `rendering.py`
- **AND** `plugins/` 下按 PluginType 分子目录（`entry/`, `index/`, `llm/`, `maintenance/`, `postprocess/`, `preprocess/`, `trim/`），**不**存在 `plugins/phase1/` 或 `plugins/phase2/`

#### Scenario: 根目录存在 docs 目录

- **WHEN** 项目初始化完成
- **THEN** 根目录下存在 `docs/` 目录，包含 `INDEX.md`、`getting-started.md`、`architecture.md`、`graph-model-design.md`、`plugin-system.md`、`api-reference.md`、`configuration.md`、`mcp-server.md`、`memory-agent.md`、`evaluation.md`、`faq.md`、`known-issues.md`
- **AND** 不存在 `core-flows.md`、`technical-design.md`、`memory-agent-design.md`（已删除，内容迁入统一图模型文档体系）

#### Scenario: 根目录存在开源文档

- **WHEN** 项目初始化完成
- **THEN** 根目录下存在 `LICENSE`、`CONTRIBUTING.md`、`CHANGELOG.md`

#### Scenario: core 目录包含 mcs.py 和 builder.py

- **WHEN** 检查 `mcs/core/` 目录
- **THEN** 存在 `mcs.py`（MCS 类定义，双 Manager 架构）和 `builder.py`（MCSBuilder 抽象类）

#### Scenario: presets 目录存在

- **WHEN** 检查 `mcs/presets/` 目录
- **THEN** 存在 `__init__.py`（导出 `Phase1Builder`、`create_mcs`、`get_phase1_plugin_registry`）和 `phase1.py`

#### Scenario: 各子目录有 __init__.py

- **WHEN** 检查 `mcs/` 及其所有子目录
- **THEN** 每个目录下都存在 `__init__.py` 文件，使其成为有效的 Python 包

#### Scenario: 测试和示例目录与包同级

- **WHEN** 检查项目根
- **THEN** 存在 `tests/` 和 `examples/` 目录，与 `mcs/` 同级，**不**位于 `mcs/` 内部

#### Scenario: 根目录不含概念层文档

- **WHEN** 检查根目录下的 .md 文件
- **THEN** 仅存在 `README.md`（入口文档）、`CLAUDE.md`（项目宪法）、`CONTRIBUTING.md`（贡献指南）、`CHANGELOG.md`（变更历史）
- **AND** 不存在 `MCS技术方案.md`、`测试方案.md`、`PENDING_FIXES.md`（已迁入 `docs/` 或删除）

### Requirement: 接口层完整性

The system SHALL provide all interfaces as ABC classes with `@abstractmethod`-decorated method stubs, organized under `mcs/interfaces/` by PluginType and extension concern.

#### Scenario: 接口文件覆盖全部 PluginType 与扩展接口

- **WHEN** 检查 `mcs/interfaces/` 目录
- **THEN** 存在与 13 类 PluginType 对应的接口文件（如 `entry_plugin.py`, `trim_plugin.py`, `arbitration_plugin.py`, `postprocess_plugin.py`, `write_preprocess_plugin.py`, `query_preprocess_plugin.py`, `compaction_plugin.py`, `index.py`, `llm.py`, `maintenance.py`）
- **AND** 存在扩展接口 `node_extension.py`, `edge_extension.py`, `storage_schema_ext.py`, `priority_scorer.py`
- **AND** **不**存在已废弃的 `pipeline_hook.py` 或 `query_hook.py`

#### Scenario: ABC 接口方法签名完整

- **WHEN** 加载任一接口模块
- **THEN** 其暴露的 ABC 类拥有对应接口的全部抽象方法，方法体为 `pass`，并带 `@abstractmethod` 装饰器

#### Scenario: 接口可被实例化错误捕获

- **WHEN** 尝试直接实例化任一接口的 ABC 类（不提供具体子类）
- **THEN** Python 抛出 `TypeError`，提示"Can't instantiate abstract class"

### Requirement: 核心引擎骨架

The system SHALL provide skeleton implementations of all core engine modules listed in `architecture.md` §2.

#### Scenario: Node 和 Edge dataclass 定义

- **WHEN** 加载 `mcs.entities.graph`
- **THEN** 存在 `Node` dataclass（字段 `id, name, content, node_class, extensions`）和 `Edge` dataclass（字段 `source_id, target_id, id, type, priority, extensions`）

#### Scenario: MCS 类为瘦门面（双 Manager）

- **WHEN** 加载 `mcs.core.mcs`
- **THEN** 存在 `MCS` class，作为瘦门面暴露 `ingest`, `query`, `run_maintenance`, `register_plugin`, `register_shared_plugin`, `unregister_plugin`, `get_plugin`, `show`, `shutdown`
- **AND** 存在 `write_manager` 和 `read_manager` 两个 `PluginManager` 实例
- **AND** **不**存在 `initialize` 或 `persist_full` 方法（初始化由 Builder 完成、持久化由写入管线阶段 ⑦ 完成）

#### Scenario: MCSBuilder 抽象类定义在 core/builder.py

- **WHEN** 加载 `mcs.core.builder`
- **THEN** 存在 `MCSBuilder` ABC，包含抽象方法 `get_plugin_class` 和具体方法 `build`

#### Scenario: MCSConfig 包含 shared/write/read 字段

- **WHEN** 加载 `mcs.entities.config`
- **THEN** `MCSConfig` dataclass 包含字段 `shared_plugins`、`write_plugins`、`read_plugins`、`write_llm`、`read_llm`
- **AND** **不**包含旧 `plugins` 字段

### Requirement: Python 包配置

The system SHALL be a valid PEP 517/518 Python package configured via `pyproject.toml`.

#### Scenario: pyproject.toml 元数据完整

- **WHEN** 解析 `pyproject.toml`
- **THEN** `[project]` 表包含 `name = "mcs"`, `version`, `requires-python = ">=3.10"`, `dependencies` 列表, `description`

#### Scenario: 可被 pip 安装

- **WHEN** 在干净 venv 中执行 `pip install -e .`
- **THEN** 命令以成功状态码退出，且 `python -c "import mcs"` 在该 venv 中可用

#### Scenario: 运行时依赖声明完整

- **WHEN** 检查 `pyproject.toml` 的 `dependencies` 字段
- **THEN** 至少包含 `openai`（DeepSeek 兼容客户端）和 `jieba`（中文分词），版本约束宽松（如 `>=1.0,<2.0`）

#### Scenario: 包发现配置正确

- **WHEN** 解析 `pyproject.toml`
- **THEN** `[tool.setuptools.packages.find]`（或等价配置）的 `include` 字段限定为 `["mcs*"]`，避免把根目录 markdown 文件误打包

---

### Requirement: 测试框架集成

The system SHALL include pytest configuration ready for test additions.

#### Scenario: pytest 配置位于 pyproject.toml

- **WHEN** 解析 `pyproject.toml`
- **THEN** 存在 `[tool.pytest.ini_options]` 表，至少配置 `testpaths = ["tests"]`

#### Scenario: tests 目录可执行

- **WHEN** 在项目根目录运行 `pytest`
- **THEN** 命令以成功状态码退出（即使没有任何测试用例），**不**报配置错误或导入错误

#### Scenario: conftest.py 占位存在

- **WHEN** 检查 `tests/` 目录
- **THEN** 存在 `conftest.py` 文件（可为空），为 Phase 1 fixtures 提供挂载点

---

### Requirement: 代码风格工具配置

The system SHALL include ruff configuration in `pyproject.toml`.

#### Scenario: ruff 配置存在

- **WHEN** 解析 `pyproject.toml`
- **THEN** 存在 `[tool.ruff]` 表，至少配置 `line-length` 和 `target-version`

#### Scenario: ruff 在骨架代码上零错误

- **WHEN** 在项目根目录运行 `ruff check .`
- **THEN** 命令以成功状态码退出，零 lint 错误

---

### Requirement: 业务逻辑零实现

The system SHALL contain no business logic in the skeleton; all logic implementation is deferred to subsequent changes.

#### Scenario: 具体类方法体仅为占位

- **WHEN** 检查任一具体类（非 ABC、非 dataclass）的方法体
- **THEN** 方法体为 `pass`、`raise NotImplementedError("Phase 1 implementation pending")`，或仅为字段赋值，**不**包含业务算法实现

#### Scenario: 干净环境下导入无副作用

- **WHEN** 在干净环境（无 API key、无网络）下执行 `python -c "import mcs"`
- **THEN** 导入成功，**不**触发任何 LLM API 调用、网络请求或外部 I/O

#### Scenario: 不存在隐式实现

- **WHEN** grep 代码中是否有数据库连接、HTTP 客户端、文件读写的实际调用
- **THEN** 仅在 `__init__` / `initialize` 等明显占位位置出现，未出现在 ingest / query 等业务方法中

---

### Requirement: Git 与 README 集成

The system SHALL include `.gitignore` and updated `README.md`.

#### Scenario: .gitignore 排除标准项

- **WHEN** 检查 `.gitignore`
- **THEN** 至少排除 `__pycache__/`, `*.pyc`, `.venv/`, `*.egg-info/`, `*.db`, `.pytest_cache/`, `.ruff_cache/`, IDE 配置目录（`.idea/`, `.vscode/`）

#### Scenario: README 含项目简介与快速开始

- **WHEN** 打开 `README.md`
- **THEN** 包含项目简介（一段话）、对 `docs/architecture.md`（及文档索引 `docs/INDEX.md`）的引用、`pip install -e .` 安装步骤、`pytest` 执行命令
- **AND** **不**引用已删除的 `docs/technical-design.md` 或 `docs/core-flows.md`

### Requirement: 插件按 PluginType 组织

The system SHALL organize built-in plugins into subdirectories under `mcs/plugins/` by their `PluginType`, rather than by development phase.

#### Scenario: 每类插件落对应类型子目录

- **WHEN** 检查 `mcs/plugins/`
- **THEN** 存在按 PluginType 分的子目录 `entry/`, `index/`, `llm/`, `maintenance/`, `postprocess/`, `preprocess/`, `trim/`
- **AND** 各子目录下的插件文件属于该类型（如 `trim/priority_trim.py` 属 TRIM、`llm/deepseek_llm.py` 属 LLM、`maintenance/dedup_maintenance.py` 属 MAINTENANCE、`entry/hub_fallback.py` 属 ENTRY）
- **AND** 每个子目录含 `__init__.py`

#### Scenario: 不存在 phase 分期目录

- **WHEN** 检查 `mcs/plugins/`
- **THEN** **不**存在 `phase1/` 或 `phase2/` 目录


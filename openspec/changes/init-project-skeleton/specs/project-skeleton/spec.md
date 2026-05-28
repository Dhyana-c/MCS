## ADDED Requirements

### Requirement: 项目目录结构

The system SHALL maintain the directory structure defined in `architecture.md` §8.

#### Scenario: 根目录存在 mcs 包

- **WHEN** 项目初始化完成
- **THEN** 根目录下存在 `mcs/` 目录，包含子目录 `core/`, `interfaces/`, `plugins/phase1/`, `plugins/phase2/`, `prompts/`, `utils/`

#### Scenario: 各子目录有 __init__.py

- **WHEN** 检查 `mcs/` 及其所有子目录
- **THEN** 每个目录下都存在 `__init__.py` 文件，使其成为有效的 Python 包

#### Scenario: 测试和示例目录与包同级

- **WHEN** 检查项目根
- **THEN** 存在 `tests/` 和 `examples/` 目录，与 `mcs/` 同级，**不**位于 `mcs/` 内部

---

### Requirement: 接口层完整性

The system SHALL provide all interfaces defined in `architecture.md` §3 as ABC classes with `@abstractmethod`-decorated method stubs.

#### Scenario: 8 个接口文件齐全

- **WHEN** 检查 `mcs/interfaces/` 目录
- **THEN** 存在 `storage.py`, `index.py`, `llm.py`, `node_extension.py`, `pipeline_hook.py`, `query_hook.py`, `storage_schema_ext.py`, `maintenance.py` 共 8 个接口文件

#### Scenario: ABC 接口方法签名完整

- **WHEN** 加载任一接口模块
- **THEN** 其暴露的 ABC 类拥有 `architecture.md` §3 中列出的全部抽象方法，方法体为 `pass`，并带 `@abstractmethod` 装饰器

#### Scenario: 接口可被实例化错误捕获

- **WHEN** 尝试直接实例化任一接口的 ABC 类（不提供具体子类）
- **THEN** Python 抛出 `TypeError`，提示"Can't instantiate abstract class"

---

### Requirement: 核心引擎骨架

The system SHALL provide skeleton implementations of all core engine modules listed in `architecture.md` §2.

#### Scenario: Node 和 Edge dataclass 定义

- **WHEN** 加载 `mcs.core.graph`
- **THEN** 存在 `Node` dataclass（字段 `id, name, content, role, extensions`）和 `Edge` dataclass（字段 `source_id, target_id, direction`）

#### Scenario: GraphStore 类骨架存在

- **WHEN** 加载 `mcs.core.graph`
- **THEN** 存在 `GraphStore` class，方法 `add_node / get_node / update_node / delete_node / add_edge / get_neighbors / get_edge / delete_edge / get_subgraph / get_all_nodes / get_all_edges` 均存在，方法体抛 `NotImplementedError`

#### Scenario: WritePipeline 状态机定义完整

- **WHEN** 加载 `mcs.core.write_pipeline`
- **THEN** 存在 `WritePipelineState` Enum（含 9 个状态值：`INGEST_START`, `EXTRACTED`, `PLACE_START`, `ANCHORS_FOUND`, `EXISTENCE_CHECKED`, `CREATED_OR_MERGED`, `FANOUT_CHECKED`, `PLACE_END`, `INGEST_END`）、`HookContext` dataclass、`WritePipeline` class

#### Scenario: QueryEngine 状态机定义完整

- **WHEN** 加载 `mcs.core.query_engine`
- **THEN** 存在 `QueryPipelineState` Enum（含 7 个状态值：`QUERY_START`, `SEEDS_LOCATED`, `TRAVERSE_START`, `TRAVERSE_STEP`, `TRAVERSE_END`, `SYNTHESIZE_START`, `QUERY_END`）、`QueryContext` dataclass、`QueryEngine` class

#### Scenario: Serializer 含 get_summary helper

- **WHEN** 加载 `mcs.core.serializer`
- **THEN** `Serializer` 类暴露 `serialize()` 方法和 `get_summary()` 静态方法（即使 `serialize` 体为 NotImplementedError，`get_summary` 必须可工作）

---

### Requirement: Phase 1 插件占位

The system SHALL provide skeleton files for all 5 Phase 1 plugins listed in `architecture.md` §6.

#### Scenario: 5 个 Phase 1 插件文件齐全

- **WHEN** 检查 `mcs/plugins/phase1/`
- **THEN** 存在 `alias_index.py`, `summary.py`, `source_tracking.py`, `sqlite_storage.py`, `deepseek_llm.py`

#### Scenario: 插件类继承正确的接口

- **WHEN** 加载任一 Phase 1 插件类
- **THEN** 类继承 `Plugin` 基类和 `architecture.md` §6 中声明的对应接口（例：`AliasIndexPlugin` 继承 `Plugin + IndexInterface + NodeExtensionInterface + PipelineHookInterface`）

#### Scenario: Source 数据类位置正确

- **WHEN** 检查 `Source` 数据类
- **THEN** `Source` 定义在 `mcs.plugins.phase1.source_tracking`，且**不**出现在 `mcs.core.graph` 或其他核心模块

#### Scenario: 插件 name 属性与文件名匹配

- **WHEN** 加载任一 Phase 1 插件类
- **THEN** 其 `name` 类属性的值（如 `"alias_index"`）与模块文件名一致（`alias_index.py`）

---

### Requirement: Phase 2 插件预留

The system SHALL reserve placeholder files for all 6 Phase 2 plugins listed in `architecture.md` §7 without any implementation.

#### Scenario: Phase 2 占位文件齐全

- **WHEN** 检查 `mcs/plugins/phase2/`
- **THEN** 存在 `event_layer.py`, `versioning.py`, `confidence.py`, `timeseries_entry.py`, `gc.py`, `arbitration.py`

#### Scenario: Phase 2 文件仅含 docstring

- **WHEN** 打开任一 Phase 2 占位文件
- **THEN** 文件**仅含**模块 docstring 声明"Phase 2，本期不实现，见 architecture.md §7"，**不**包含任何 import、类定义或函数定义

---

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
- **THEN** 包含项目简介（一段话）、对 `MCS技术方案.md` 和 `openspec/specs/architecture.md` 的引用、`pip install -e .` 安装步骤、`pytest` 执行命令

## MODIFIED Requirements

### Requirement: 项目目录结构

The system SHALL maintain the directory structure defined in `architecture.md` §8, including the `docs/` directory for L2 conceptual documents and root-level open source files.

#### Scenario: 根目录存在 mcs 包

- **WHEN** 项目初始化完成
- **THEN** 根目录下存在 `mcs/` 目录，包含子目录 `entities/`, `core/`, `interfaces/`, `plugins/phase1/`, `plugins/phase2/`, `presets/`, `prompts/`, `utils/`

#### Scenario: 根目录存在 docs 目录

- **WHEN** 项目初始化完成
- **THEN** 根目录下存在 `docs/` 目录，包含 `INDEX.md`、`architecture.md`、`core-flows.md`、`technical-design.md`、`known-issues.md`、`faq.md`

#### Scenario: 根目录存在开源文档

- **WHEN** 项目初始化完成
- **THEN** 根目录下存在 `LICENSE`、`CONTRIBUTING.md`、`CHANGELOG.md`

#### Scenario: core 目录包含 mcs.py 和 builder.py

- **WHEN** 检查 `mcs/core/` 目录
- **THEN** 存在 `mcs.py`（MCS 类定义，双 Manager 架构）和 `builder.py`（MCSBuilder 抽象类）

#### Scenario: presets 目录存在

- **WHEN** 检查 `mcs/presets/` 目录
- **THEN** 存在 `__init__.py` 和 `phase1.py`

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

### Requirement: 核心引擎骨架

The system SHALL provide skeleton implementations of all core engine modules listed in `architecture.md` §2.

#### Scenario: Node 和 Edge dataclass 定义

- **WHEN** 加载 `mcs.entities.graph`
- **THEN** 存在 `Node` dataclass（字段 `id, name, content, role, extensions`）和 `Edge` dataclass（字段 `source_id, target_id, direction`）

#### Scenario: GraphStore 类骨架存在

- **WHEN** 加载 `mcs.entities.graph`
- **THEN** 存在 `GraphStore` class，方法 `add_node / get_node / update_node / delete_node / add_edge / get_neighbors / get_edge / delete_edge / get_subgraph / get_all_nodes / get_all_edges` 均存在，方法体抛 `NotImplementedError`

#### Scenario: MCS 类定义在 core/mcs.py（双 Manager）

- **WHEN** 加载 `mcs.core.mcs`
- **THEN** 存在 `MCS` class，包含 `__init__`、`initialize`、`ingest`、`query`、`persist_full` 方法
- **AND** 存在 `write_manager` 和 `read_manager` 两个 `PluginManager` 实例

#### Scenario: MCSBuilder 抽象类定义在 core/builder.py

- **WHEN** 加载 `mcs.core.builder`
- **THEN** 存在 `MCSBuilder` ABC，包含抽象方法 `get_plugin_class` 和具体方法 `build`

#### Scenario: MCSConfig 包含 shared/write/read 字段

- **WHEN** 加载 `mcs.entities.config`
- **THEN** `MCSConfig` dataclass 包含字段 `shared_plugins`、`write_plugins`、`read_plugins`、`write_llm`、`read_llm`
- **AND** **不**包含旧 `plugins` 字段

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
- **THEN** `Source` 定义在 `mcs.plugins.phase1.source_tracking`，且**不**出现在 `mcs.entities.graph` 或其他核心模块

#### Scenario: 插件 name 属性与文件名匹配

- **WHEN** 加载任一 Phase 1 插件类
- **THEN** 其 `name` 类属性的值（如 `"alias_index"`）与模块文件名一致（`alias_index.py`）

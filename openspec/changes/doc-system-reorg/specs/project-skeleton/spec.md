## MODIFIED Requirements

### Requirement: 项目目录结构

The system SHALL maintain the directory structure defined in `architecture.md` §8, including the `docs/` directory for L2 conceptual documents.

#### Scenario: 根目录存在 mcs 包

- **WHEN** 项目初始化完成
- **THEN** 根目录下存在 `mcs/` 目录，包含子目录 `core/`, `interfaces/`, `plugins/phase1/`, `plugins/phase2/`, `presets/`, `prompts/`, `utils/`

#### Scenario: 根目录存在 docs 目录

- **WHEN** 项目初始化完成
- **THEN** 根目录下存在 `docs/` 目录，包含 `INDEX.md`、`architecture.md`、`core-flows.md`、`testing-plan.md`、`known-issues.md`、`CHANGELOG.md`

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
- **THEN** 仅存在 `README.md`（入口文档）和 `CLAUDE.md`（项目宪法）
- **AND** 不存在 `MCS技术方案.md`、`测试方案.md`、`PENDING_FIXES.md`（已迁入 `docs/`）

## ADDED Requirements

### Requirement: Bench 目录按评测类型分类

Bench 评测 SHALL 按类型组织在顶层 `bench/` 目录下，每种评测类型一个子目录。每个子目录 SHALL 包含 `scripts/`、`reports/` 子目录，可包含 `config/`、`data/`、`outputs/` 子目录。

#### Scenario: 目录结构完整性

- **WHEN** 创建新的评测类型目录
- **THEN** 目录下 MUST 包含 `scripts/` 和 `reports/` 子目录

#### Scenario: 评测代码位于 bench/ 目录

- **WHEN** 评测代码需要被外部导入
- **THEN** 代码 SHALL 位于 `bench/` 目录下（如 `bench/multihop_rag/`、`bench/hotpotqa/`、`bench/plugins/`），启动脚本通过 `from bench.xxx import ...` 调用

### Requirement: 启动脚本无命令行参数

每个启动脚本 SHALL 硬编码所有配置参数，不依赖命令行参数。不同实验配置 SHALL 使用不同的脚本文件。

#### Scenario: 脚本直接运行

- **WHEN** 运行 `python bench/multihop-rag/scripts/run_baseline.py`
- **THEN** 脚本 SHALL 无需任何命令行参数即可完成评测

#### Scenario: 不同配置使用不同脚本

- **WHEN** 需要运行文档级重排评测
- **THEN** SHALL 使用 `run_doc_rerank.py` 而非在基线脚本上传递参数

### Requirement: 启动脚本命名规范

脚本文件名 SHALL 使用 `run_<实验配置>.py` 格式，名称清晰表达评测类型和配置差异。

#### Scenario: 命名格式

- **WHEN** 创建新的启动脚本
- **THEN** 文件名 SHALL 匹配 `run_<kebab-case-描述>.py` 格式

### Requirement: 输出文件集中管理

评测输出（数据库、日志、结果）SHALL 输出到对应评测类型的 `outputs/` 目录下，不污染项目根目录。

#### Scenario: 输出路径

- **WHEN** 运行启动脚本
- **THEN** 所有输出文件 SHALL 写入 `bench/<评测类型>/outputs/<实验名>/` 目录

### Requirement: 报告归档

评测报告 SHALL 存放在对应评测类型的 `reports/` 目录，并提交到版本控制。

#### Scenario: 报告存放

- **WHEN** 生成评测报告
- **THEN** 报告 SHALL 存放在 `bench/<评测类型>/reports/` 目录下

### Requirement: 根目录散落文件清理

项目根目录下散落的 bench 相关临时文件（`multihop_*.db`、`multihop_output_*`、`_run_*.py`）SHALL 被移动或删除。

#### Scenario: 临时数据库文件

- **WHEN** 项目根目录存在 `multihop_*.db` 文件
- **THEN** 这些文件 SHALL 移动到 `bench/multihop-rag/outputs/` 或删除

#### Scenario: 临时启动脚本

- **WHEN** 项目根目录存在 `_run_*.py` 文件
- **THEN** 这些文件 SHALL 迁移到 `bench/multihop-rag/scripts/` 后删除原文件

### Requirement: 评测目录 README

每个评测类型目录 SHALL 包含 `README.md`，说明评测目的、数据来源、运行方式和指标口径。

#### Scenario: README 内容

- **WHEN** 查看 `bench/multihop-rag/README.md`
- **THEN** 文档 SHALL 包含评测目的、数据下载说明、可用脚本列表和指标说明
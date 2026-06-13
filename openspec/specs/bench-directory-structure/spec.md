## Purpose
定义 bench 评测目录按类型分类的组织结构，规定启动脚本无命令行参数、命名规范及输出文件集中管理。

## Requirements

### Requirement: 评测目录结构

The system SHALL maintain a bench directory structure with `bench/README.md` serving as the evaluation entry document.

#### Scenario: bench 顶层目录结构

- **WHEN** 检查 `bench/` 目录
- **THEN** 存在 `multihop_rag/`（含 `scripts/`、`reports/`、`README.md`）和 `plugins/`
- **AND** 存在顶层 `README.md`（评测入口文档）

#### Scenario: bench README 为评测入口

- **WHEN** 打开 `bench/README.md`
- **THEN** 包含目录结构说明、评测类型导航、各评测类型简介
- **AND** 不包含与具体评测类型重复的详细配置说明
- **AND** 每种评测类型通过链接指向各自的 `README.md`

#### Scenario: 评测报告集中管理

- **WHEN** 检查评测报告文件位置
- **THEN** 所有实验报告位于 `bench/<评测类型>/reports/` 目录下

---

### Requirement: 启动脚本无命令行参数

每个启动脚本 SHALL 硬编码所有配置参数，不依赖命令行参数。不同实验配置 SHALL 使用不同的脚本文件。

#### Scenario: 脚本直接运行

- **WHEN** 运行 `python bench/multihop_rag/scripts/run_baseline.py`
- **THEN** 脚本 SHALL 无需任何命令行参数即可完成评测

#### Scenario: 不同配置使用不同脚本

- **WHEN** 需要运行文档级重排评测
- **THEN** SHALL 使用 `run_doc_rerank.py` 而非在基线脚本上传递参数

---

### Requirement: 启动脚本命名规范

脚本文件名 SHALL 使用 `run_<实验配置>.py` 格式，名称清晰表达评测类型和配置差异。

#### Scenario: 命名格式

- **WHEN** 创建新的启动脚本
- **THEN** 文件名 SHALL 匹配 `run_<kebab-case-描述>.py` 格式

---

### Requirement: 输出文件集中管理

评测输出（数据库、日志、结果）SHALL 输出到对应评测类型的 `outputs/` 目录下，不污染项目根目录。

#### Scenario: 输出路径

- **WHEN** 运行启动脚本
- **THEN** 所有输出文件 SHALL 写入 `bench/<评测类型>/outputs/<实验名>/` 目录

---

### Requirement: 根目录散落文件清理

项目根目录下散落的 bench 相关临时文件（`multihop_*.db`、`multihop_output_*`、`_run_*.py`）SHALL 被移动或删除。

#### Scenario: 临时数据库文件

- **WHEN** 项目根目录存在 `multihop_*.db` 文件
- **THEN** 这些文件 SHALL 移动到 `bench/multihop_rag/outputs/` 或删除

#### Scenario: 临时启动脚本

- **WHEN** 项目根目录存在 `_run_*.py` 文件
- **THEN** 这些文件 SHALL 迁移到 `bench/multihop_rag/scripts/` 后删除原文件

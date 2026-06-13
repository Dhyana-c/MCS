## MODIFIED Requirements

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

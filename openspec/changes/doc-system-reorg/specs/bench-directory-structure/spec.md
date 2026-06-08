## MODIFIED Requirements

### Requirement: 评测目录结构

The system SHALL maintain a bench directory structure with clear separation between user-facing entry docs (`bench/`) and library API docs (`mcs/bench/`).

#### Scenario: bench 顶层目录结构

- **WHEN** 检查 `bench/` 目录
- **THEN** 存在 `multihop-rag/`（含 `scripts/`、`reports/`、`README.md`）和 `hotpotqa/`（含 `README.md`）
- **AND** 存在顶层 `README.md`（评测入口文档）

#### Scenario: bench README 为评测入口

- **WHEN** 打开 `bench/README.md`
- **THEN** 包含目录结构说明、评测类型导航、各评测类型简介
- **AND** 不包含与具体评测类型重复的详细配置说明
- **AND** 每种评测类型通过链接指向各自的 `README.md`

#### Scenario: mcs/bench README 为 API 文档

- **WHEN** 打开 `mcs/bench/README.md`
- **THEN** 包含 HotpotQA 评测的 API 用法（Python 代码示例、数据结构说明）
- **AND** 不包含启动脚本说明（职责在 `bench/` 目录）
- **AND** 不包含与 `bench/multihop-rag/README.md` 重复的内容

#### Scenario: 评测报告集中管理

- **WHEN** 检查评测报告文件位置
- **THEN** 所有实验报告位于 `bench/<评测类型>/reports/` 目录下
- **AND** 不存在 `mcs/bench/MULTIHOP_RERANK_REPORT.md`（已迁入 `bench/multihop-rag/reports/`）

#### Scenario: MultiHop-RAG 文档不重复

- **WHEN** 检查 MultiHop-RAG 相关文档
- **THEN** 评测详细说明仅存在于 `bench/multihop-rag/README.md`
- **AND** 不存在 `mcs/bench/MULTIHOP_RAG.md`（已合并）

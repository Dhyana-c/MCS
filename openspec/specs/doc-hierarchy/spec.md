## Purpose

定义文档层级规范与索引体系：三层划分（L1 入口层 / L2 概念层 / L3 规范层）、docs/ 目录结构、README 精简规范、开源必备文档、文档链接完整性。

## ADDED Requirements

### Requirement: 文档总索引

系统 SHALL 在 `docs/INDEX.md` 提供统一的文档导航入口，覆盖项目中所有文档的定位信息。

#### Scenario: INDEX.md 存在且可导航

- **WHEN** 用户打开 `docs/INDEX.md`
- **THEN** 文件包含按层级（L1 入口层 / L2 概念层 / L3 规范层）组织的文档索引
- **AND** 每个条目包含文档名称、路径、一句话描述
- **AND** 所有路径使用相对链接且链接目标存在

#### Scenario: INDEX.md 涵盖主要文档

- **WHEN** 遍历项目中所有 .md 文档文件
- **THEN** 每个主要文档在 INDEX.md 中有且仅有一个条目
- **AND** 条目按所属层级正确归类
- **AND** stub 文件、`.openspec.yaml` 等辅助文件不需要索引

### Requirement: docs 目录结构

系统 SHALL 维护 `docs/` 目录，集中管理 L2 概念层文档。

#### Scenario: docs 目录包含必需文件

- **WHEN** 检查 `docs/` 目录
- **THEN** 存在以下文件：`INDEX.md`、`architecture.md`、`core-flows.md`、`technical-design.md`、`known-issues.md`、`faq.md`

#### Scenario: docs 目录不含 L3 规范层文档

- **WHEN** 检查 `docs/` 目录下所有 .md 文件
- **THEN** 无文件包含 SHALL/MUST 形式的契约性规范定义
- **AND** 无文件与 `openspec/specs/` 下的 spec 内容逐字重复

### Requirement: README 精简

根目录 `README.md` SHALL 仅包含项目定位、核心赌注、快速开始、文档导航、评测导航、贡献指南链接、许可证链接。

#### Scenario: README 结构符合开源惯例

- **WHEN** 检查 `README.md` 内容
- **THEN** 包含以下章节：项目定位、核心赌注、快速开始、文档、评测、贡献、许可证
- **AND** 不包含架构详解、管线段定义、插件列表等架构详解内容
- **AND** 不包含评测 CLI 参数、评测架构、输出文件等评测详解内容
- **AND** 不包含项目结构树、模式配置表、开发状态、依赖列表等

#### Scenario: README 包含文档导航

- **WHEN** 检查 `README.md` "文档"章节
- **THEN** 链接到 `docs/INDEX.md`

#### Scenario: README 包含开源文档导航

- **WHEN** 检查 `README.md`
- **THEN** "贡献"章节链接到 `CONTRIBUTING.md`
- **AND** "许可证"章节链接到 `LICENSE`

### Requirement: 架构总览文档

系统 SHALL 在 `docs/architecture.md` 提供架构总览，解释系统整体设计而非仅索引 spec。

#### Scenario: 架构总览包含关键设计解释

- **WHEN** 打开 `docs/architecture.md`
- **THEN** 包含以下内容：系统定位、双层结构、核心不变量、读写管线总览、插件体系、目录结构
- **AND** 每个主题提供理解性解释，不仅列出 spec 链接

#### Scenario: 与 spec 边界清晰

- **WHEN** 比较 `docs/architecture.md` 与 `openspec/specs/` 下的 spec
- **THEN** architecture.md 解释"为什么"和"怎么理解"
- **AND** spec 定义"必须满足什么"（SHALL/MUST 契约）
- **AND** 无内容逐字重复

### Requirement: 核心流程文档

系统 SHALL 在 `docs/core-flows.md` 提供核心流程的统一说明。

#### Scenario: 核心流程覆盖读写管线

- **WHEN** 打开 `docs/core-flows.md`
- **THEN** 包含写入流程（ingest 7 段管线）和查询流程（query 5 段管线）的说明
- **AND** 包含图演化流程（聚类裂变、hub 复用、归纳重组）

### Requirement: 技术方案文档

系统 SHALL 在 `docs/technical-design.md` 保留完整技术方案，从 `MCS技术方案.md` 迁入。

#### Scenario: 技术方案完整性

- **WHEN** 打开 `docs/technical-design.md`
- **THEN** 内容与原 `MCS技术方案.md` 完整一致（迁移不删减）

#### Scenario: 原文件已删除

- **WHEN** 检查根目录
- **THEN** 不存在 `MCS技术方案.md`

### Requirement: 已知问题文档

系统 SHALL 在 `docs/known-issues.md` 仅记录未修复的问题。

#### Scenario: 已知问题列表不含已修复项

- **WHEN** 打开 `docs/known-issues.md`
- **THEN** 所有条目均为未修复的开放问题
- **AND** 不包含已标记为 [x] 的已修复项

### Requirement: 变更历史索引

系统 SHALL 在根目录 `CHANGELOG.md` 提供变更历史的概览索引。

#### Scenario: CHANGELOG 涵盖所有归档 change

- **WHEN** 打开 `CHANGELOG.md`
- **THEN** 包含 `openspec/changes/archive/` 下所有归档 change 的条目
- **AND** 每个条目包含日期、change 名称、简要描述

#### Scenario: CHANGELOG 按时间倒序

- **WHEN** 检查 `CHANGELOG.md` 条目顺序
- **THEN** 条目按归档日期从新到旧排列

### Requirement: 贡献指南

系统 SHALL 在根目录 `CONTRIBUTING.md` 提供贡献指南。

#### Scenario: CONTRIBUTING.md 包含必要内容

- **WHEN** 打开 `CONTRIBUTING.md`
- **THEN** 包含环境搭建、开发流程、提交规范
- **AND** 内容可操作（步骤明确，不空洞）

### Requirement: 许可证

系统 SHALL 在根目录 `LICENSE` 提供开源许可证。

#### Scenario: LICENSE 存在

- **WHEN** 检查根目录
- **THEN** 存在 `LICENSE` 文件，内容为有效的开源许可证文本

### Requirement: 文档链接完整性

所有文档中的内部链接 SHALL 指向有效目标。

#### Scenario: 无断裂链接

- **WHEN** 检查项目中所有 .md 文件中的相对链接
- **THEN** 每个链接的目标文件在项目中存在
- **AND** 迁移后原位置的 stub 文件正确指向新位置

#### Scenario: 迁移后原位置留 stub

- **WHEN** 文档从位置 A 迁移到位置 B
- **THEN** 位置 A 保留 stub 文件，内容为"本文档已迁至 [B 的相对路径]"
- **AND** stub 文件不包含过期内容

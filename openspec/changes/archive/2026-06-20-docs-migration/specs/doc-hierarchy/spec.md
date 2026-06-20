# Spec Delta: doc-hierarchy（文档体系迁移——对齐统一图模型）

> 本 delta 在现有 `doc-hierarchy` 能力上，删除旧模型专属文档需求、更新 docs 目录必需文件清单、补齐统一图模型下的新文档契约。

## MODIFIED Requirements

### Requirement: docs 目录结构

系统 SHALL 维护 `docs/` 目录，集中管理面向使用者与贡献者的概念层 / 参考层文档。

#### Scenario: docs 目录包含必需文件

- **WHEN** 检查 `docs/` 目录
- **THEN** 存在以下文件：`INDEX.md`、`getting-started.md`、`architecture.md`、`graph-model-design.md`、`plugin-system.md`、`api-reference.md`、`configuration.md`、`mcp-server.md`、`memory-agent.md`、`evaluation.md`、`faq.md`、`known-issues.md`
- **AND** 不存在 `core-flows.md`、`technical-design.md`、`memory-agent-design.md`（已删除，内容迁入统一图模型文档体系）

#### Scenario: docs 目录不含 L3 规范层文档

- **WHEN** 检查 `docs/` 目录下所有 .md 文件
- **THEN** 无文件包含 SHALL/MUST 形式的契约性规范定义
- **AND** 无文件与 `openspec/specs/` 下的 spec 内容逐字重复

### Requirement: 架构总览文档

系统 SHALL 在 `docs/architecture.md` 提供架构总览，解释系统整体设计而非仅索引 spec，且全文仅使用统一图模型术语。

#### Scenario: 架构总览包含关键设计解释

- **WHEN** 打开 `docs/architecture.md`
- **THEN** 包含以下内容：系统定位、双层结构（核心图 / 事件层）、核心不变量、读写管线总览、插件体系、目录结构
- **AND** 每个主题提供理解性解释，不仅列出 spec 链接

#### Scenario: 与 spec 边界清晰

- **WHEN** 比较 `docs/architecture.md` 与 `openspec/specs/` 下的 spec
- **THEN** architecture.md 解释"为什么"和"怎么理解"
- **AND** spec 定义"必须满足什么"（SHALL/MUST 契约）
- **AND** 无内容逐字重复

#### Scenario: 统一图模型术语零残留

- **WHEN** 全文搜索 `relation_model` / `property_graph` / `attribute_node` / `role="hub"` / 边语境的 `kind` / `label`
- **THEN** 匹配数为 0
- **AND** 可找到 `node_class`（4 类节点）、`type`（关联 / 互斥）、`extensions["hub"]` 标记、`get_relations`、载重规则的说明

## ADDED Requirements

### Requirement: getting-started.md 上手指南

系统 SHALL 在 `docs/getting-started.md` 提供从零开始的完整上手路径：安装 → 创建实例 → 写入 → 查询 → 持久化 → MCP 接入 → Agent 启动。

#### Scenario: 新用户可按文档走通

- **WHEN** 新用户按文档步骤操作
- **THEN** 可完成安装、写入、查询的完整流程

#### Scenario: 所有代码示例可运行

- **WHEN** 复制文档中的代码示例执行
- **THEN** 无 ImportError / AttributeError（API 与当前代码一致）

### Requirement: plugin-system.md 插件体系说明

系统 SHALL 在 `docs/plugin-system.md` 覆盖全部 14 类 PluginType、每类的接口签名与职责、注册机制、生命周期、自定义插件开发示例与内置插件清单。

#### Scenario: PluginType 完整枚举

- **WHEN** 查看文档中 PluginType 列表
- **THEN** 与 `mcs/core/plugin.py` 中 `PluginType` 枚举的全部成员一致（兼容别名 `PREPROCESS` 单独标注为已废弃）

#### Scenario: 自定义插件可按文档开发

- **WHEN** 开发者按文档"自定义插件"段落编写插件
- **THEN** 插件可成功注册并被 MCS 调用

### Requirement: api-reference.md API 参考

系统 SHALL 在 `docs/api-reference.md` 覆盖 MCS 类的全部公开方法、核心数据类、Builder 模式与 MCP 工具清单。每个方法 MUST 列出签名、参数说明、返回值。

#### Scenario: 公开方法无遗漏且归属准确

- **WHEN** 对比文档"MCS 公开方法"列表与 `mcs/core/mcs.py` 的公开方法
- **THEN** 一一对应
- **AND** 不在 `mcs.py` 门面上的方法（如 `get_related_events`，实际在 query engine / store）不被列为 MCS 方法，而注明其真实归属

#### Scenario: 数据类字段完整

- **WHEN** 查看文档中 Node / Edge / Decision / EventData / SourceData / Subgraph 的字段说明
- **THEN** 与 `mcs/entities/` 中对应 dataclass 字段一致

### Requirement: memory-agent.md Agent 说明

系统 SHALL 在 `docs/memory-agent.md` 覆盖 ReAct loop 架构、5 个导航工具（learn / search / associate / reason / recall）、MemoryStore 单线程封装、FastAPI 后端端点、启动方式、与 MCP Server 的区别。

#### Scenario: 工具清单完整

- **WHEN** 对比文档工具列表与 `mcs_agent/loop.py` 中 `MEMORY_TOOLS` 定义
- **THEN** 工具名称一一对应

#### Scenario: 启动方式可操作

- **WHEN** 按文档环境变量设置启动 Agent
- **THEN** 可成功启动并访问 `/chat` 端点

### Requirement: evaluation.md 评测说明

系统 SHALL 在 `docs/evaluation.md` 覆盖评测框架结构、multihop-rag 评测流程与指标、extraction_quality 评测与运行方式。

#### Scenario: 指标定义清晰

- **WHEN** 阅读 Hit@k / Recall@k / MAP@k / MRR@k 的定义
- **THEN** 与 `bench/multihop_rag/metrics.py` 实现一致

#### Scenario: 运行命令可执行

- **WHEN** 按文档运行评测命令
- **THEN** 命令存在且参数与 runner 一致（dry-run / mock 模式不依赖特定 LLM API key）

### Requirement: configuration.md 无 relation_model 引用

`docs/configuration.md` MUST NOT 包含 `relation_model` 配置项、示例或 provenance 拒绝说明。

#### Scenario: YAML 示例无 relation_model

- **WHEN** 查看文档中所有 YAML 示例
- **THEN** 不含 `relation_model` 键

#### Scenario: provenance 说明无 relation_model 拒绝

- **WHEN** 查看文档中 provenance 相关段落
- **THEN** 不含 `relation_model` 不一致硬拒描述

### Requirement: mcp-server.md 包含完整工具清单

`docs/mcp-server.md` 的工具表 MUST 列出当前 MCP server 实际注册（`build_fastmcp` 中
`@mcp_server.tool()`）的全部工具，且 MUST NOT 列出未注册的工具。

#### Scenario: 工具表与代码一致

- **WHEN** 对比文档工具表与 `mcs_mcp/server.py` 中 `@mcp_server.tool()` 注册的工具
- **THEN** 工具名称一一对应（当前为 `query`、`ingest` 两个）
- **AND** 不把仅存在于 MCS 门面、未注册为 MCP 工具的方法（如 `run_maintenance`）列为 MCP 工具

### Requirement: faq.md 对齐统一图模型

`docs/faq.md` 中关于核心不变量与边语义的回答 MUST 与 `graph-model-design.md` 一致。

#### Scenario: 不变量与边语义表述准确

- **WHEN** 阅读不变量与边语义相关问答
- **THEN** 不变量表述为"任意节点的活跃双向视图 ≤ T"，边语义为 `关联` / `互斥`，且无 `property_graph` / `relation_model` 等旧概念残留

### Requirement: graph-model-design.md 版本与状态标注

`docs/graph-model-design.md` 的版本与状态标注 MUST 反映当前实现状态。当设计已实现并合并到 main 时，MUST NOT 标注"草稿"或"尚未实现"。

#### Scenario: 已实现的设计文档

- **WHEN** 对应代码已合并到 main
- **THEN** 文档版本标注为 `v1.0` 或更高，且不含"草稿"/"尚未实现"措辞

## REMOVED Requirements

### Requirement: 核心流程文档

**Reason**: `docs/core-flows.md` 被 `graph-model-design.md` §5（写入 / 查询流程）完全覆盖且更详细更正确；维护两份会造成分歧。该文件随本 change 删除。

**Migration**: 读者参阅 `graph-model-design.md` §5.1（写入管线）与 §5.2（查询管线）。

### Requirement: 技术方案文档

**Reason**: `docs/technical-design.md` 整篇基于旧双模式模型（属性节点 / label 边 / role / relation_model），与统一图模型根本矛盾、无法修补。该文件随本 change 删除。

**Migration**: 读者参阅 `graph-model-design.md`（统一图模型的权威设计）。

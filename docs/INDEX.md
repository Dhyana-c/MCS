# MCS 文档索引

> 本索引覆盖 MCS 项目所有文档，按三层层级组织：入口层（定位）→ 概念层（理解）→ 规范层（约束）。

## L1 入口层

| 文档 | 路径 | 说明 |
|------|------|------|
| README | [README.md](../README.md) | 项目定位、核心赌注、快速开始 |
| 贡献指南 | [CONTRIBUTING.md](../CONTRIBUTING.md) | 环境搭建、开发流程、提交规范 |
| 变更历史 | [CHANGELOG.md](../CHANGELOG.md) | 所有归档 change 的按时间倒序索引 |
| 许可证 | [LICENSE](../LICENSE) | 开源许可证 |

## L2 概念层

> 集中在 `docs/` 目录，理解性文档——解释"为什么"和"怎么理解"。

| 文档 | 路径 | 说明 |
|------|------|------|
| 架构总览 | [architecture.md](architecture.md) | 系统定位、双层结构、核心不变量、插件体系、目录结构 |
| 核心流程 | [core-flows.md](core-flows.md) | 写入管线（7 段）、查询管线（5 段）、图演化（聚类裂变/hub 复用） |
| 技术方案 | [technical-design.md](technical-design.md) | 完整的机制设计文档（双层结构、边语义、社区合并、激活扩散等） |
| 已知问题 | [known-issues.md](known-issues.md) | 未修复的开放问题 |
| 常见问题 | [faq.md](faq.md) | 常见问题与解答 |
| 配置文件 | [configuration.md](configuration.md) | YAML 配置加载（preset 叠加、`${VAR}` 插值、import-path 插件、受信输入） |

## L3 规范层

> 集中在 `openspec/specs/`，约束性文档——定义"必须满足什么"（SHALL/MUST 契约）。

| 文档 | 路径 | 说明 |
|------|------|------|
| 架构索引 | [openspec/specs/architecture.md](../openspec/specs/architecture.md) | 指向各 capability spec 的导航索引 |
| Spec 索引 | [openspec/specs/INDEX.md](../openspec/specs/INDEX.md) | 按能力域分组的 spec 导航 |

### Capability Specs

| Capability | 路径 | 关注 |
|------------|------|------|
| store-interface | [spec](../openspec/specs/store-interface/spec.md) | 统一存储接口 |
| query-pipeline | [spec](../openspec/specs/query-pipeline/spec.md) | 读流程 5 段管线 |
| write-pipeline | [spec](../openspec/specs/write-pipeline/spec.md) | 写流程 7 段管线 |
| mcs-builder | [spec](../openspec/specs/mcs-builder/spec.md) | MCS 实例构建契约 |
| plugin-protocol | [spec](../openspec/specs/plugin-protocol/spec.md) | 插件接口与链语义 |
| llm-interaction | [spec](../openspec/specs/llm-interaction/spec.md) | LLM 调用统一模式 |
| subgraph-bounding | [spec](../openspec/specs/subgraph-bounding/spec.md) | 最大上下文子图不变量 |
| project-skeleton | [spec](../openspec/specs/project-skeleton/spec.md) | 项目目录结构 |

> 完整列表见 [openspec/specs/INDEX.md](../openspec/specs/INDEX.md)。

## 评测文档

| 文档 | 路径 | 说明 |
|------|------|------|
| 评测入口 | [bench/README.md](../bench/README.md) | 评测框架目录结构与类型导航 |
| MultiHop-RAG | [bench/multihop_rag/README.md](../bench/multihop_rag/README.md) | 文档级多跳检索评测说明 |

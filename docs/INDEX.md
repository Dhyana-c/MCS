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
| 上手指南 | [getting-started.md](getting-started.md) | 5 分钟跑通：安装 → 写入 → 查询 → 持久化 → MCP → Agent |
| 架构总览 | [architecture.md](architecture.md) | 系统定位、4 类节点 / 2 类边、双层结构、读写管线、插件体系、目录结构 |
| 图模型设计 | [graph-model-design.md](graph-model-design.md) | **完整、权威**的图模型与核心算法设计（v1.0，已实现） |
| 插件体系 | [plugin-system.md](plugin-system.md) | 14 类 PluginType、接口签名、注册机制、生命周期、自定义插件开发 |
| API 参考 | [api-reference.md](api-reference.md) | MCS 公开方法、核心数据类、Builder / 工厂、MCP 工具 |
| 配置文件 | [configuration.md](configuration.md) | YAML 配置加载（preset 叠加、`${VAR}` 插值、import-path 插件、受信输入） |
| MCP Server | [mcp-server.md](mcp-server.md) | MCP（stdio）server：`query` / `ingest` 工具、Claude Desktop 接入 |
| 记忆 Agent | [memory-agent.md](memory-agent.md) | ReAct loop、5 导航工具、单线程封装、FastAPI 后端、启动方式 |
| 评测 | [evaluation.md](evaluation.md) | 评测框架结构、multihop-rag 指标、extraction_quality、运行方式 |
| 常见问题 | [faq.md](faq.md) | FAQ |
| 已知问题 | [known-issues.md](known-issues.md) | 未修复的开放问题 |

## L3 规范层

> 集中在 `openspec/specs/`，约束性文档——定义"必须满足什么"（SHALL/MUST 契约）。

| 文档 | 路径 | 说明 |
|------|------|------|
| 架构索引 | [openspec/specs/architecture.md](../openspec/specs/architecture.md) | 指向各 capability spec 的导航索引 |
| Spec 索引 | [openspec/specs/INDEX.md](../openspec/specs/INDEX.md) | 按能力域分组的 spec 导航 |

### Capability Specs（节选）

| Capability | 路径 | 关注 |
|------------|------|------|
| unified-graph-schema | [spec](../openspec/specs/unified-graph-schema/spec.md) | 统一图模型机制契约 |
| store-interface | [spec](../openspec/specs/store-interface/spec.md) | 统一存储接口 |
| query-pipeline | [spec](../openspec/specs/query-pipeline/spec.md) | 读流程管线 |
| write-pipeline | [spec](../openspec/specs/write-pipeline/spec.md) | 写流程管线 |
| mcs-builder | [spec](../openspec/specs/mcs-builder/spec.md) | MCS 实例构建契约 |
| plugin-protocol | [spec](../openspec/specs/plugin-protocol/spec.md) | 插件接口与链语义 |
| subgraph-bounding | [spec](../openspec/specs/subgraph-bounding/spec.md) | 最大上下文子图不变量 |
| doc-hierarchy | [spec](../openspec/specs/doc-hierarchy/spec.md) | 文档层级规范与索引体系 |

> 完整列表见 [openspec/specs/INDEX.md](../openspec/specs/INDEX.md)。

## 评测文档

| 文档 | 路径 | 说明 |
|------|------|------|
| 评测总览 | [evaluation.md](evaluation.md) | 评测框架结构与指标定义 |
| 评测入口 | [bench/README.md](../bench/README.md) | 评测框架目录结构与类型导航 |
| MultiHop-RAG | [bench/multihop_rag/README.md](../bench/multihop_rag/README.md) | 文档级多跳检索评测说明 |

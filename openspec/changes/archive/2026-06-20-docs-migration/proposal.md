# Proposal: 文档体系迁移——对齐统一图模型

## Why

`unified-graph-schema` 已合并到 main（41/41 tasks 完成），代码已全面迁移到统一图模型（4 类节点 / 2 类边 / 无 relation_model）。但 `docs/` 目录的文档仍停留在旧模型——`architecture.md` 含 `relation_model` 双模式、`technical-design.md` 整篇基于属性节点/label 边、`core-flows.md` 被 `graph-model-design.md` 完全覆盖。开源前必须把文档对齐到当前代码。

## What Changes

### 1. 删除旧文档（3 个文件）

| 文件 | 理由 |
|------|------|
| `docs/core-flows.md` | `graph-model-design.md` §5（写入/查询流程）完全覆盖，且更详细更正确 |
| `docs/technical-design.md` | 整篇基于旧双模式模型（属性节点 / label 边 / role / relation_model），与当前代码根本矛盾，被 `graph-model-design.md` 取代 |
| `docs/memory-agent-design.md` | 基于 role/属性节点模型的实验草案，与当前 node_class 模型矛盾 |

### 2. 重写 / 保留修改（2 个文件）

| 文件 | 动作 | 说明 |
|------|------|------|
| `docs/architecture.md` | 重写 | 删 `relation_model` 双模式、`role="hub"`、provenance 拒绝；改为 `node_class`、`extensions["hub"]` 标记、`关联`/`互斥` 边类型、当前目录结构、当前插件类型 |
| `docs/graph-model-design.md` | 保留+小修 | 版本号 v0.1 草稿 → v1.0 已实现；删"尚未实现"措辞 |

### 3. 新建文档（6 个文件）

| 文件 | 层级 | 内容 |
|------|------|------|
| `docs/getting-started.md` | L1 | 5 分钟上手：安装 → 创建实例 → ingest → query → 持久化 → MCP 接入 → Agent 启动 |
| `docs/plugin-system.md` | L2 | 14 类 PluginType 逐一说明 + 接口签名 + 注册机制 + 生命周期 + 自定义插件开发指南（含示例）+ 内置插件清单 |
| `docs/api-reference.md` | L2 | MCS 公开方法（ingest / ingest_event / ingest_source / query / get_related_events / run_maintenance）+ 数据类（Node / Edge / Decision / EventData / SourceData / Subgraph / MCSConfig / TokenBudget）+ Builder 模式 + MCP Server 工具清单 |
| `docs/memory-agent.md` | L3 | Agent 架构（ReAct loop + 自有 LLM）+ 5 导航工具（learn / search / associate / reason / recall）+ learn_event + MemoryStore 单线程封装 + FastAPI 后端（/chat /health /graph/expand）+ 前端可视化 + 启动方式（环境变量）+ 与 MCP Server 的区别 |
| `docs/evaluation.md` | L3 | 评测框架结构（bench/ 目录说明）+ multihop-rag 评测（runner / builder / metrics / 脚本）+ 指标说明（Hit@k / Recall@k / MAP@k / MRR@k）+ extraction_quality 评测（概念 vs 事实抽取准确率）+ 运行方式 |
| `docs/INDEX.md` | 索引 | 重写索引，反映上述全部变更 |

### 4. 更新现有文档（3 个文件）

| 文件 | 变更 |
|------|------|
| `docs/configuration.md` | 删 `relation_model: property_graph` 示例行；删 provenance `relation_model` 拒绝段落；更新 preset 工厂参数说明 |
| `docs/mcp-server.md` | 工具表加 `ingest_event`、`ingest_source`、`run_maintenance`；验证 YAML 示例 |
| `docs/faq.md` | 不变量表述对齐（层级子节点 vs 一跳邻居）；边语义改为 `关联`/`互斥`；删残留 `property_graph` 上下文 |

### 5. 不动（1 个文件）

| 文件 | 理由 |
|------|------|
| `docs/known-issues.md` | 无模型依赖，内容仍准确 |

## 不在范围

- `README.md`：当前内容基本正确，不动
- 代码变更：本 change 纯文档，不改任何 Python 代码

> 注：`doc-hierarchy` 能力 spec 的同步**在本 change 范围内**——见 `specs/doc-hierarchy/spec.md` delta（删 `核心流程文档` / `技术方案文档`、改 `docs 目录结构` 与 `架构总览文档`、增统一图模型下的新文档契约）。否则 spec 仍要求 `core-flows.md` / `technical-design.md` 存在，与删除动作自相矛盾。

## 影响评估

- **读者**：从"过时文档 vs 正确代码"的矛盾中解脱
- **贡献者**：有清晰的插件开发指南和 API 参考
- **风险**：无代码变更，纯文档，零回归风险

## 新旧概念映射（迁移时逐文件替换）

| 旧概念 | 新概念 |
|--------|--------|
| `relation_model` | 已删除（单一模型） |
| `property_graph` / `attribute_node` | 已删除 |
| `role` (节点属性) | `node_class` (概念/事实/事件/source) |
| `role="hub"` | `extensions["hub"]` 标记 |
| `get_facts` / `get_assoc` | `get_relations` |
| `kind` / `label` (边字段) | 已删除（谓词在事实 content） |

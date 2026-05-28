---
name: phase1-knowledge-graph
description: MCS 第一期实现 - 知识图谱引擎核心功能
status: planning
phase: 1
created: 2026-05-27
---

# 第一期：知识图谱引擎

## 目标

实现 MCS 的第一期产品：一个可用于 Wiki 和企业知识库的知识图谱引擎。

核心特点：
- 不依赖 embedding，完全由 LLM 语义驱动
- 无类型邻接边，方向通过合并涌现
- 模块式架构，插件可配置

## 范围

### 包含

- 核心引擎：GraphStore、TokenBudget、Serializer、WritePipeline、QueryEngine
- 插件系统：PluginManager、接口定义
- 第一期插件：AliasIndex、SQLiteStorage、DeepSeekLLM
- Prompt 模板：概念抽取、放置判定、合并判断、遍历方向、答案合成
- 基本示例和文档

### 不包含（第二期）

- 事实层（Event Layer）
- 版本链（时间戳/置信/superseded）
- 自动 GC 和淘汰
- 矛盾检测与仲裁
- 时序召回入口
- 追问加深（可续跑遍历）

## 关键交付物

| 模块 | 文件 | 优先级 |
|------|------|--------|
| **核心引擎** | | |
| 核心图结构（Node 最小核心 + extensions） | core/graph.py | P0 |
| Token 预算 | core/token_budget.py | P0 |
| 子图序列化（含 get_summary helper） | core/serializer.py | P0 |
| 写入管线（9 状态点状态机 + HookContext） | core/write_pipeline.py | P0 |
| 查询引擎（7 状态点状态机 + QueryContext） | core/query_engine.py | P0 |
| 插件管理器（含 schema 扩展收集） | core/plugin_manager.py | P0 |
| 配置系统 | core/config.py | P0 |
| **接口层** | | |
| 存储接口 | interfaces/storage.py | P0 |
| 索引接口 | interfaces/index.py | P0 |
| LLM接口（含 generate_aliases / generate_summary） | interfaces/llm.py | P0 |
| 节点扩展接口 | interfaces/node_extension.py | P0 |
| 写入钩子接口（9 个 on_state 方法） | interfaces/pipeline_hook.py | P0 |
| 查询钩子接口（7 个 on_state 方法） | interfaces/query_hook.py | P0 |
| 存储 schema 扩展接口 | interfaces/storage_schema_ext.py | P0 |
| **Phase 1 插件（5 个）** | | |
| 别名词典（Index + NodeExt + PipelineHook） | plugins/phase1/alias_index.py | P1 |
| 摘要生成（NodeExt + PipelineHook） | plugins/phase1/summary.py | P1 |
| 出处追踪（NodeExt + PipelineHook + SchemaExt）含 Source 数据类 | plugins/phase1/source_tracking.py | P1 |
| SQLite 持久化（支持 schema 扩展） | plugins/phase1/sqlite_storage.py | P1 |
| DeepSeek LLM | plugins/phase1/deepseek_llm.py | P1 |
| **其他** | | |
| Prompt 模板（含 aliases.py / summary.py） | prompts/*.py | P1 |
| 中文分词 | utils/tokenizer.py | P2 |
| 示例代码 | examples/*.py | P2 |

## 技术约束

- 语言：Python 3.10+
- 存储：内存图 + SQLite 持久化（schema 通过 `StorageSchemaExtensionInterface` 由插件动态注册）
- LLM：DeepSeek API（抽象层，可替换）
- Token估算：第一阶段用简单估算
- **架构原则**：核心 Node 字段固定（`id / name / content / role / extensions`），可变数据全部走 `extensions`；流程定义为状态机（写入 9 个状态点 / 查询 7 个状态点），新行为通过实现钩子接口接入
- 文档修订：通过 `SourceTrackingPlugin.update_document(doc_id, new_chunks)` + 显式 `purge_orphans()` 处理，不引入版本链
- 出处追踪：由 `SourceTrackingPlugin` 实现，挂到 `node.extensions["source_tracking"]`，支持答案引用与再次摄入幂等
- 不处理时序冲突 / 矛盾事件 / 自动 GC（Phase 2 通过新增插件接入，核心引擎不动）
- 不实现查询端同名异义消歧（见 `architecture.md` §11 已知限制）

## 里程碑

1. **M1 - 核心骨架**：GraphStore + TokenBudget + Serializer
2. **M2 - 写入管线**：WritePipeline + LLM接口 + Prompt模板
3. **M3 - 查询引擎**：QueryEngine + Index接口
4. **M4 - 插件系统**：PluginManager + 第一期插件
5. **M5 - 验证测试**：简单领域验证（如"深度学习基础"）

## 验收标准

- 能摄入一段文本，自动抽取概念并放置到图中
- 能处理 10+ 段文本，图结构能自组织（降扇出、合并）
- 能通过词法入口或顶点导航定位种子节点
- 能执行语义遍历，收敛到相关区域
- 能合成回答并返回
- 数据能持久化到 SQLite 并重新加载
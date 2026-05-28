# MCS - Maximum-Context Subgraph

一种面向单一领域、由大模型语义驱动的知识图谱与检索引擎。不依赖 embedding / 向量检索，靠大模型直接阅读"装得下的局部子图"来完成关系发现、聚类与查询。

## 核心赌注

**知识有足够的局部性**——回答一个问题所需要的概念，在图里彼此靠近，几跳语义游走就能连到一起。

这对"已能被人类整理成可教结构的领域"（物理、工程、各类有教科书/本体的学科）最成立；对跨领域综合、强语境依赖、矛盾常态化的知识（法律、历史、文化）会发紧。

## 设计原则

- **大模型是唯一的语义引擎**：所有"这俩概念相关吗""谁更一般""该往哪走"的判断，由大模型阅读真实内容做出，不用向量相似度兜底
- **知识有局部性**：核心机制围绕"局部子图装得下"设计
- **写入不保证唯一，靠惰性合并兜底**：宁可不合，不可错合
- **边只表达邻接，含义在说法里**：一种无类型边 + 自然语言版本承载含义，不做谓词归一
- **事件层是历史与兜底**：概念层是当前物化视图，可重放找回

## 架构

```
┌─────────────────────────────────────────────────────────────────────┐
│                        应用层 (CLI / API / SDK)                     │
├─────────────────────────────────────────────────────────────────────┤
│                        配置层 (MCSConfig)                           │
├─────────────────────────────────────────────────────────────────────┤
│                     插件管理器 (PluginManager)                       │
├─────────────────────────────────────────────────────────────────────┤
│                        核心引擎 (Core Engine)                       │
│    GraphStore | TokenBudget | Serializer | WritePipeline | Query   │
├─────────────────────────────────────────────────────────────────────┤
│                        接口层 (Interfaces)                          │
│     Storage | Index | LLM | NodeExtension | PipelineHook | QueryHook │
├─────────────────────────────────────────────────────────────────────┤
│                        插件层 (Plugins)                             │
│   Phase1: AliasIndex, Summary, SourceTracking, SQLite, DeepSeekLLM │
│   Phase2: EventLayer, Versioning, Confidence, GC, ...              │
└─────────────────────────────────────────────────────────────────────┘
```

模块式架构，核心引擎稳定不变，功能通过插件配置组合。第一期（知识图谱）和第二期（记忆系统）通过插件叠加切换，互不替换。

### 双层结构

- **概念层（Concept Layer）**：从事实中提炼的语义网络，MCS 主体。一般有向图，允许环
- **事实层（Event Layer）**：原始事实的线性时序日志，只追加不修改（第二期实现）

### 只有一种边：无类型邻接边

不预设方向，初始双向。方向/非对称通过社区合并涌现——一片区域塌缩成星型时，枢纽→成员的方向才定下来。关系的"含义"放在属性节点的版本说法里，不放在边上。

## 快速开始

```python
from mcs import MCS, MCSConfig

# 知识图谱模式
config = MCSConfig.knowledge_graph()
config.plugin_configs["deepseek_llm"]["api_key"] = "your-api-key"

mcs = MCS(config)

# 摄入文本
mcs.ingest("深度学习是机器学习的一个子领域，它使用多层神经网络来学习数据的表示。")
mcs.ingest("卷积神经网络是一种专门处理网格状数据的深度学习模型。")

# 查询
answer = mcs.query("什么是深度学习？")
print(answer)
```

### 手动注册插件

```python
from mcs import MCS
from mcs.plugins.phase1 import AliasIndexPlugin, SQLiteStoragePlugin, DeepSeekLLMPlugin

mcs = MCS()
mcs.register_plugin(AliasIndexPlugin())
mcs.register_plugin(SQLiteStoragePlugin(path="my_knowledge.db"))
mcs.register_plugin(DeepSeekLLMPlugin(api_key="your-api-key"))
mcs.initialize()
```

## 两期产品

| | 第一期：知识图谱 | 第二期：记忆系统 |
|---|---|---|
| 场景 | Wiki / 企业知识库 | 对话记忆 / 事件追踪 |
| 知识特征 | 静态/半静态 | 动态/时序 |
| 属性更新 | 简单覆盖 | 版本链保留 |
| 维护方式 | 手动 | 自动 GC |
| 入口策略 | 词法 + 顶点兜底 | + 时序召回 |
| 插件 | AliasIndex, Summary, SourceTracking, SQLite, DeepSeekLLM (5) | + EventLayer, Versioning, Confidence, TimeSeriesEntry, GC, Arbitration (6) |

第二期通过插件叠加，不替换第一期核心引擎。

## 项目结构

```
mcs/
├── core/                     # 核心引擎
│   ├── config.py             # MCSConfig
│   ├── graph.py              # GraphStore, Node, Edge
│   ├── token_budget.py       # TokenBudget
│   ├── serializer.py         # Serializer
│   ├── write_pipeline.py     # WritePipeline
│   ├── query_engine.py       # QueryEngine
│   └── plugin_manager.py     # PluginManager
│
├── interfaces/               # 插件接口
│   ├── storage.py            # StorageInterface
│   ├── index.py              # IndexInterface
│   ├── llm.py                # LLMInterface
│   ├── node_extension.py     # NodeExtensionInterface
│   ├── pipeline_hook.py      # PipelineHookInterface (9 states)
│   ├── query_hook.py         # QueryHookInterface (7 states)
│   ├── storage_schema_ext.py # StorageSchemaExtensionInterface
│   └── maintenance.py        # MaintenanceInterface
│
├── plugins/                  # 插件实现
│   ├── base.py               # Plugin 基类
│   ├── phase1/               # 第一期插件 (5 个)
│   │   ├── alias_index.py
│   │   ├── summary.py
│   │   ├── source_tracking.py  # 含 Source 数据类
│   │   ├── sqlite_storage.py
│   │   └── deepseek_llm.py
│   └── phase2/               # 第二期插件（预留，6 个）
│
├── prompts/                  # Prompt 模板
├── utils/                    # 工具函数
└── examples/                 # 示例
```

## 文档

- [技术方案](MCS技术方案.md) - 完整的机制设计文档
- [架构设计](openspec/specs/architecture.md) - 模块式架构详细设计
- [测试方案](测试方案.md) - 分阶段验证测试计划
- [第一期提案](openspec/changes/phase1-knowledge-graph/proposal.md) - 第一期实现计划

## 依赖

- Python 3.10+
- SQLite（内置）
- DeepSeek API（或兼容 OpenAI SDK 的 LLM 服务）

## 开发状态

第一期（知识图谱引擎）：**项目骨架已搭建**（所有方法体 `raise NotImplementedError`），下一步按 [phase1-knowledge-graph](openspec/changes/phase1-knowledge-graph/) change 填充实现。

### 安装与验证骨架

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS / Linux
pip install -e ".[dev]"
pytest                          # 跑骨架冒烟测试
ruff check .                    # 代码风格检查
```
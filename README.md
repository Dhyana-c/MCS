# MCS - Maximum-Context Subgraph

一个**可扩展的记忆系统**——面向单一领域，由大模型语义驱动，把零散文本组织成图结构的语义记忆。不依赖 embedding / 向量检索，靠大模型直接阅读"装得下的局部子图"完成关系发现、聚类与召回。

MCS 默认返回相关节点集合（`List[Node]`），不是自然语言答案。它专注于"记忆本身"，把合成答案、多轮对话、追问加深等留给上层（RAG / Agent / Chatbot）。

## 核心赌注

**知识有足够的局部性**——回答一个问题所需要的概念，在图里彼此靠近，几跳语义游走就能连到一起。

这对"已能被人类整理成可教结构的领域"（物理、工程、各类有教科书/本体的学科）最成立；对跨领域综合、强语境依赖、矛盾常态化的知识（法律、历史、文化）会发紧。

## 设计原则

- **大模型是唯一的语义引擎**：所有"这俩概念相关吗""谁更一般""该往哪走"的判断，由大模型阅读真实内容做出，不用向量相似度兜底
- **知识有局部性**：核心机制围绕"局部子图装得下"设计
- **写入不保证唯一，靠惰性合并兜底**：宁可不合，不可错合
- **边只表达邻接，含义在说法里**：一种无类型边 + 自然语言版本承载含义，不做谓词归一
- **事件层是历史与兜底**：概念层是当前物化视图，可重放找回
- **读写对称、流程可插**：读写共享"前置链 + 主体 + 后置链"模板，写入复用读流程做关联节点定位

## 架构

```
┌───────────────────────────────────────────────────────────────────────┐
│                        应用层 (CLI / API / SDK)                       │
├───────────────────────────────────────────────────────────────────────┤
│                        配置层 (MCSConfig)                             │
├───────────────────────────────────────────────────────────────────────┤
│                     插件管理器 (PluginManager)                         │
├───────────────────────────────────────────────────────────────────────┤
│                        核心引擎 (Core Engine)                         │
│   GraphStore | TokenBudget | ContextRenderer                         │
│   WritePipeline (7 段) | QueryEngine (5 段)                          │
├───────────────────────────────────────────────────────────────────────┤
│                        接口层 (Interfaces)                            │
│   LLM | Storage | Index | NodeExtension                              │
│   EntryPlugin | TrimPlugin | ArbitrationPlugin                       │
│   PostprocessPlugin | CompactionPlugin                               │
├───────────────────────────────────────────────────────────────────────┤
│                        插件层 (Plugins)                               │
│   AliasEntry, HubFallback, PriorityTrim, Summary,                    │
│   SourceTracking, FanoutReducer, SummaryRegen,                       │
│   SQLite, DeepSeekLLM, ClaudeLLM, OllamaLLM                        │
└───────────────────────────────────────────────────────────────────────┘
```

模块式架构：核心引擎稳定不变，功能通过插件链组合。Phase 1（知识图谱模式）与未来 Phase 2（事件层 + 版本化 + 自动 GC）通过追加插件切换，互不替换。

### 读写工作流（对称）

```
读 (RECALL)                          写 (INGEST)
─────────────────────                ─────────────────────
input: query, [ctx]                  input: text

① 前置插件链 (可选)                  ① 前置插件链 (可选)
② 种子定位 (入口插件链+裁剪)         ② 关联节点定位 ◄─ 复用读流程
③ 语义理解 Loop (BFS + 上限)         ③ 概念提取 (LLM)
④ 仲裁 (≤1, 单一职责)                ④ 关系判定 (LLM) → DecisionList
⑤ 后置处理链 (0..N, 串联)            ⑤ 图更新 (无 LLM)
                                     ⑥ 压缩判定插件链 (条件触发)
                                     ⑦ 自动落盘 (StorageInterface 增量持久化)

OUTPUT: List[Node]                   OUTPUT: 图状态更新
```

### 双层结构

- **概念层（Concept Layer）**：从事实中提炼的语义网络，MCS 主体。一般有向图，允许环
- **事实层（Event Layer）**：原始事实的线性时序日志，只追加不修改（Phase 2 实现）

### 只有一种边：无类型邻接边

不预设方向，初始双向。方向/非对称通过社区合并涌现——一片区域塌缩成星型时，枢纽→成员的方向才定下来。关系的"含义"放在属性节点的版本说法里，不放在边上。

## 快速开始

```python
from mcs import MCS, MCSConfig

# 知识图谱模式（默认配置含 11 个 Phase 1 插件）
config = MCSConfig.knowledge_graph()
config.plugin_configs["deepseek_llm"]["api_key"] = "your-api-key"

mcs = MCS(config)
mcs.initialize()    # 实例化插件、初始化、构建管线

# 摄入文本 → 自动抽概念、定位、入图
mcs.ingest("深度学习是机器学习的一个子领域，它使用多层神经网络来学习数据的表示。")
mcs.ingest("卷积神经网络是一种专门处理网格状数据的深度学习模型。")

# 查询 → 默认返回相关节点集合
nodes = mcs.query("什么是深度学习？")
for n in nodes:
    print(n.name, "—", n.content[:80])

# 若需要合成自然语言答案，挂一个 PostprocessPlugin 到后置处理链
```

### 切换到 Claude / Anthropic 后端

```python
from mcs import MCS, MCSConfig

# 把默认 LLM 从 DeepSeek 换成 Claude（其余 10 个插件不变）
config = MCSConfig.knowledge_graph(llm="claude")
config.plugin_configs["claude_llm"].update({
    "auth_token": "your-anthropic-token",     # 优先于 api_key
    "model": "claude-3-5-sonnet-latest",
    "base_url": "https://api.anthropic.com",   # 可指向 Anthropic 兼容网关
})

mcs = MCS(config)
mcs.initialize()
```

> 需先安装可选依赖：`pip install -e ".[claude]"`。token 建议经环境变量 / `.env`（已 gitignore）注入，**不要写进代码或提交到仓库**；若已泄露请尽快轮换。

### 使用本地 Ollama 后端（零 token 成本）

Ollama 是本地推理引擎，让 MCS 能跑本地模型，把按 token 计费的 build/eval 变成零成本实验路径。

**前置条件：**
1. 安装 Ollama：https://ollama.ai
2. 启动服务：`ollama serve`
3. 拉取模型：`ollama pull qwen3.5:9b`（或其他支持的模型）

**配置示例：**

```python
from mcs import MCS, MCSConfig

# 使用本地 Ollama 后端
config = MCSConfig.knowledge_graph(llm="ollama")
config.plugin_configs["ollama_llm"].update({
    "base_url": "http://192.168.31.134:11434/v1",  # Ollama 服务地址
    "model": "qwen3.5:9b",                         # 已拉取的模型名称
})

mcs = MCS(config)
mcs.initialize()

# 零 token 成本摄入知识
mcs.ingest("深度学习是机器学习的一个子领域...")
nodes = mcs.query("什么是深度学习？")
```

**适用场景：**
- 大量实验迭代（build 变成 time-bound 而非 cost-bound）
- 离线 / 隐私场景
- 与 build-cost-reduction 协同：本地探索 + 云端定稿验证

**已知风险：**
- 小本地模型（7–9B）结构化 JSON 输出可靠性弱于云端 → 解析失败可能更多（lenient parser 已缓解）
- 推理较慢 → timeout 默认 120s
- 需本地安装 Ollama + 模型拉取

### 不带 API key 跑通

`examples/basic_usage.py` 和 `examples/wiki_example.py` 默认走 mock 模式
（不需要 API key、不联网）。详见 [`examples/README.md`](examples/README.md)。

### 自动持久化

MCS 默认开启自动落盘（`auto_persist=True`）。每次 `ingest()` 完成后，变更的节点和边会自动持久化到 SQLite。重启应用时，`initialize()` 会自动从数据库加载已有数据。

```python
from mcs import MCS, MCSConfig

# 默认配置已启用 sqlite_storage 和 auto_persist
config = MCSConfig.knowledge_graph()
config.plugin_configs["sqlite_storage"]["path"] = "my_memory.db"

mcs = MCS(config)
mcs.initialize()  # 自动从 my_memory.db 加载已有数据

mcs.ingest("新知识...")  # 自动落盘到 my_memory.db
```

禁用自动落盘（用于纯内存测试场景）：

```python
config = MCSConfig(auto_persist=False)
```

```bash
python examples/basic_usage.py
# 或加真实 LLM:
# MCS_LLM_MODE=real DEEPSEEK_API_KEY=sk-... python examples/basic_usage.py
```

### 手动注册插件

```python
from mcs import MCS
from mcs.plugins.phase1 import (
    AliasEntryPlugin, HubFallbackEntryPlugin, PriorityTrimPlugin,
    SummaryPlugin, SourceTrackingPlugin,
    SQLiteStoragePlugin, DeepSeekLLMPlugin,
)

mcs = MCS()
mcs.register_plugin(AliasEntryPlugin())          # priority=100
mcs.register_plugin(HubFallbackEntryPlugin())    # priority=0
mcs.register_plugin(PriorityTrimPlugin())
mcs.register_plugin(SummaryPlugin())
mcs.register_plugin(SourceTrackingPlugin())
mcs.register_plugin(SQLiteStoragePlugin({"path": "my_memory.db"}))
mcs.register_plugin(DeepSeekLLMPlugin({"api_key": "your-api-key"}))
mcs.initialize()
```

## 模式与配置

| | 知识图谱模式 (Phase 1) | 记忆系统模式 (Phase 2，规划中) |
|---|---|---|
| 场景 | Wiki / 企业知识库 | 对话记忆 / 事件追踪 |
| 知识特征 | 静态/半静态 | 动态/时序 |
| 属性更新 | 简单覆盖 | 版本链保留 |
| 维护方式 | 手动 | 自动 GC |
| 入口插件 | AliasEntry + HubFallback | + TimeSeriesEntry |
| 仲裁 | 无（accumulated 直通） | LLMArbitration |
| 默认输出 | `List[Node]` | `List[Node]` |
| 压缩链 | FanoutReducer + SummaryRegen | + EventLayer / Versioning / GC |

Phase 2 通过插件叠加，不替换 Phase 1 核心引擎。

## 项目结构

```
mcs/
├── core/                       # 核心引擎
│   ├── config.py               # MCSConfig
│   ├── graph.py                # GraphStore, Node, Edge
│   ├── token_budget.py         # TokenBudget
│   ├── context_renderer.py     # ContextRenderer (按 purpose 渲染)
│   ├── write_pipeline.py       # WritePipeline (7 段) + WriteContext + DecisionList
│   ├── query_engine.py         # QueryEngine (5 段) + QueryContext
│   └── plugin_manager.py       # PluginManager
│
├── bench/                      # 评测框架
│   ├── __init__.py             # 模块入口
│   ├── hotpot.py               # HotpotQA 评测核心
│   └── README.md               # 评测框架说明
│
├── interfaces/                 # 插件接口
│   ├── storage.py              # StorageInterface
│   ├── index.py                # IndexInterface
│   ├── llm.py                  # LLMInterface (call + 9 purposes)
│   ├── node_extension.py       # NodeExtensionInterface (+ render 贡献)
│   ├── entry_plugin.py         # EntryPluginInterface
│   ├── trim_plugin.py          # TrimPluginInterface
│   ├── arbitration_plugin.py   # ArbitrationPluginInterface
│   ├── postprocess_plugin.py   # PostprocessPluginInterface
│   ├── compaction_plugin.py    # CompactionPluginInterface
│   ├── storage_schema_ext.py   # StorageSchemaExtensionInterface
│   └── maintenance.py          # MaintenanceInterface
│
├── plugins/                    # 插件实现
│   ├── base.py                 # Plugin 基类
│   ├── phase1/                 # Phase 1 默认插件
│   │   ├── alias_index.py      # AliasIndex (NodeExt) + AliasEntry (EntryPlugin)
│   │   ├── hub_fallback.py     # HubFallbackEntry (兜底)
│   │   ├── priority_trim.py    # PriorityTrim
│   │   ├── summary.py
│   │   ├── source_tracking.py  # 含 Source 数据类
│   │   ├── fanout_reducer.py   # CompactionPlugin
│   │   ├── summary_regen.py    # CompactionPlugin
│   │   ├── sqlite_storage.py
│   │   ├── deepseek_llm.py     # 厂商适配（OpenAI 兼容，不含 prompt 模板）
│   │   ├── claude_llm.py       # 厂商适配（Anthropic Messages，不含 prompt 模板）
│   │   └── ollama_llm.py       # 厂商适配（本地 Ollama，OpenAI 兼容端点）
│   └── phase2/                 # Phase 2 插件（预留）
│
├── prompts/                    # 9 个 purpose 的默认 prompt (system + template + parser)
├── utils/                      # 工具函数
└── examples/                   # 示例
```

> Phase 1 实施已就位（接口、核心引擎、11 个默认插件、9 个 prompt 模板、115 个测试全过）；详见 [phase1-implement-unified-workflow](openspec/changes/archive/2026-05-30-phase1-implement-unified-workflow/) 的 tasks.md。

## 文档

### 架构契约（按 capability）
- [query-pipeline](openspec/specs/query-pipeline/spec.md) - 读流程 5 段管线契约
- [write-pipeline](openspec/specs/write-pipeline/spec.md) - 写流程 6 段管线契约
- [plugin-protocol](openspec/specs/plugin-protocol/spec.md) - 5 类插件接口契约
- [llm-interaction](openspec/specs/llm-interaction/spec.md) - LLM 调用统一模式契约
- [project-skeleton](openspec/specs/project-skeleton/spec.md) - 项目目录结构契约
- [architecture.md](openspec/specs/architecture.md) - 架构索引

### 底层设计
- [MCS技术方案.md](MCS技术方案.md) - 完整的机制设计文档
- [测试方案.md](测试方案.md) - 分阶段验证测试计划

### Change 记录
- [unified-workflow-architecture](openspec/changes/archive/) - 工作流架构定义（已归档）
- [phase1-implement-unified-workflow](openspec/changes/archive/2026-05-30-phase1-implement-unified-workflow/) - Phase 1 完整实施（已归档）

## 依赖

- Python 3.10+
- SQLite（内置）
- DeepSeek API（或兼容 OpenAI SDK 的 LLM 服务）
- Anthropic Claude API（可选：`pip install -e ".[claude]"`；也支持 Anthropic 兼容网关）
- Ollama（可选：本地推理引擎，零 token 成本；需单独安装）
- ujson（用于 HotpotQA 评测脚本）

## HotpotQA 评测

MCS 提供 HotpotQA 多跳问答端到端评测框架，用于定量验证"几跳语义游走能否连到一起"的核心假设。

### 快速评测

```bash
# 安装评测依赖
pip install -e ".[dev]"

# 设置 API key
export DEEPSEEK_API_KEY=sk-...  # 或 set DEEPSEEK_API_KEY=sk-... (Windows)

# dry-run 模式查看预估 token 消耗
python -m mcs.bench.hotpot --dry-run --subset 100

# 正式评测（100 条子集）
python -m mcs.bench.hotpot --subset 100 --output ./bench_output

# 使用 Claude 后端
export ANTHROPIC_API_KEY=sk-ant-...
python -m mcs.bench.hotpot --subset 100 --llm claude
```

### CLI 参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--subset` | 100 | 评测子集大小（0 表示全量 7405 条） |
| `--llm` | deepseek | LLM 后端（deepseek / claude） |
| `--output` | ./bench_output | 输出目录 |
| `--dry-run` | False | 仅估算 token，不执行 LLM 调用 |
| `--no-resume` | False | 从头开始，忽略进度文件 |
| `--strategy` | uniform | 采样策略（uniform / proportional） |
| `--data-path` | D:\code\hotpot\hotpot_dev_distractor_v1.json | 数据文件路径 |
| `--eval-script-dir` | D:\code\hotpot | hotpot_evaluate_v1.py 所在目录 |

### 输出文件

评测完成后，`output_dir` 包含：

- `predictions.json` - 预测结果 `{answer: {_id: str}, sp: {_id: [[title, sent_idx], ...]}}`
- `gold_subset.json` - 子集 gold 文件
- `metrics.json` - 指标结果 `{em, f1, sp_em, sp_f1, joint_em, joint_f1}`
- `progress.json` - 已完成的 `_id` 列表（断点续跑）

### 评测架构

每条 HotpotQA 数据创建独立 MCS 实例（`:memory:` 存储），避免跨条污染。评测流程：

1. 加载 HotpotQA dev_distractor 数据
2. 按 type（bridge/comparison）分层采样
3. 每条数据：10 个段落 ingest → query → 提取 answer + supporting_facts
4. 输出预测 + gold 子集 → 计算官方指标

详见 [`mcs/bench/README.md`](mcs/bench/README.md)。

## 开发状态

**架构定义**：新统一工作流架构已通过 OpenSpec change 落定（4 个 capability，36 项 Requirement，已归档）。

**代码实现**：Phase 1（知识图谱模式）已全部就位——核心引擎按新 5/6 段管线运行，11 个默认插件可用，9 个 purpose 的默认 prompt 已注册。mock 模式 examples 可立即跑通。

### 安装与验证

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS / Linux
pip install -e ".[dev]"
pytest                          # 跑全部测试
ruff check .                    # 代码风格检查
python examples/basic_usage.py  # mock 模式跑通示例
```

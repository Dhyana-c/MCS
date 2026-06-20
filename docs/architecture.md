# MCS 架构总览

> 本文档是 MCS 的**理解性文档**，解释"为什么"和"怎么理解"。契约性定义（SHALL/MUST）见
> `openspec/specs/` 下的 capability spec；**完整、权威的图模型与算法设计见
> [graph-model-design.md](graph-model-design.md)**。本文不与二者逐字重复，只给系统级的全景。

## 系统定位

MCS（**M**aximum **C**ontext **S**ubgraph，最大上下文子图）把知识组织成图，并维持一条硬不变量，
使任意节点的**活跃双向视图**永远放得进一个 LLM 上下文窗口。导航、归纳、查询都建立在此之上。

MCS **不依赖 embedding / 向量检索**，靠大模型直接阅读"装得下的局部子图"完成关系发现、聚类与召回。
核心赌注是：**知识有足够的局部性**——回答一个问题所需的概念，在图里彼此靠近，几跳语义游走就能连到一起。

`query()` 默认返回一个 **`Subgraph`**（选中的节点 + 选中的 `关联` / `互斥` 边），而不是自然语言答案。
MCS 专注"记忆本身"，把合成答案、多轮对话、追问加深留给上层（RAG / Agent / Chatbot）；后处理插件可把
`Subgraph` 转成其他形态（如自然语言字符串）。

## 核心不变量

MCS 维持一条硬不变量：

> **任意节点的活跃双向视图（top-priority 的 {关系边 + 层级邻居}，截断后）渲染 token ≤ T。**

- **活跃双向视图** = 该节点的 `关联` / `互斥` 边（两端可达，端点含事实节点）+ 聚类涌现的下钻层级邻居。
- **"有界"指活跃 / 渲染视图，不指存储**：存储可保留低优先级长尾，靠优先级沉底 / 遗忘降权；溢出靠归纳
  （聚类裂变）、优先级截断（关系侧）、遗忘降权收敛。
- **为什么需要它**：LLM 上下文有限。若某节点的一跳邻域超过 T，LLM 就无法一次性"读完"邻居来做判断
  （聚类、导航、归纳），系统便失去语义引擎的地基。不变量保证：无论图如何增长，任意节点的"局部视野"
  永远装得下。

两条铁律支撑它：

1. **估算口径 == 渲染口径**：判断"活跃视图是否超 T"的估算，必须与 `context_renderer` 实际渲染逐字一致
   （同字段、`name==content` 去重、含关系边渲染 token）。用更少字段低估会漏判、直接破坏不变量。
2. **归纳必须 LLM 语义**：中间组织中心由 `decide_hub` 语义归纳，禁止用连通分量 / Louvain 等纯图聚类替代
   （语义边稀疏时聚不出有意义的类）。

## 数据模型：4 类节点 / 2 类边

节点按**结构行为**分 4 类（不引入领域 type——人物 / 地点 / 组织等是 `extensions` 软标签）：

| `node_class` | 是什么 | 怎么产生 | 进核心组织（聚类） |
|---|---|---|:--:|
| **概念** | 名词性事物（人 / 地点 / 对象 / 抽象概念） | LLM 语义抽取 | 是 |
| **事实** | 一句命题，**谓词落在其 `content`**；可被事件背书、可与事实互斥 | LLM 语义抽取 | 是（只重组不合并） |
| **事件** | 时间轴上的一次发生 | **规则**入库，不经 LLM | 否（事件层） |
| **source** | 原始资料 / 文件 / 段落，按类型切分保真 | **规则**入库，不经 LLM | 否（叶子） |

边只有 2 类（登记制、谨慎增加）：

- **关联**（结构基础边，`source → target`）：连接事实与端点、概念间关联、聚类形成的"组织中心 ↔ 成员"。
  **无 `kind`、无开放 `label`**——开放谓词落事实节点 `content`（谓词落点）。一条只存一份，但两端邻接都索引到它
  （反查、双向可达）。
- **互斥**（当前唯一语义类型）：两条事实相互排斥，事实 ↔ 事实。

**没有独立的"层级"边**：组织层级是聚类的产物，用 `关联` 边 + 中心节点的 `hub` **标记**表达。`hub` 只用于
反查 / 可观测，**无算法含义、非节点类、非 role**；渲染给 LLM 时 hub 节点与普通节点无异。

> 谓词为什么落事实 `content`、而不做 label 边？因为事实要做**一等节点**才能被事件背书、被互斥连接——
> 边连不了边。详见 [graph-model-design.md](graph-model-design.md) §3。

## 双层结构：核心图 / 事件层

MCS 把图分成两层，**载重命根**是"核心不反查事件"：

- **核心图**（概念 + 事实）：有界，参与聚类与活跃视图。
- **事件层**（事件）：**事件 → 核心**方向单向绑入（背书 / 提及），**核心不反查事件**，不聚类、时间倒排截断。

为什么核心不反查事件？否则最热节点（尤其"用户 / 我"）会把全部事件漏回核心、撑爆活跃视图、并污染优先级
截断样本。这条规则在 store 层落实：**核心节点侧 `get_relations` MUST 过滤事件边**（事件侧 `get_relations`
仍可达核心）。需要出处时，按需做 `事实 → 事件` 的定向查询（`get_related_events`）。

**产生方式分工**：概念 / 事实靠 LLM 语义抽取；事件 / source 由**规则**入库、不经 LLM。

## 守门：改图即把关

不变量靠**守门**维持——**任何改图操作后**（写入 / 连边 / 合并 / 读修复）检查受影响节点（尤其虚拟根
`__seed_root__`）的出边侧层级视图：≤ T 放行；**即将超 T 即主动触发聚类裂变**。

- **聚类裂变（一进多出）= 知识重组**：取中心 + 下钻侧全部成员（不变量保证一次装得下）→ `decide_hub`
  分成多个语义内聚社区 → 每社区按 ① 合并同义 ② 找关键概念 ③ 概括新概念 三方式之一重组 → 中心一步收敛。
  **关系边（关联 / 互斥）不被波及**——裂变只动组织层级；对**事实**节点只重组不合并（合并会断背书 / 互斥）。
- **hub 复用（边吸收）**：新组织中心 H 生成后，若某节点 X 的下钻成员 ⊇ H 的全部成员，把 X 改为直连 H，
  减边、减扇出、复用已有 hub。
- **read-repair（读时收敛）**：查询工作集里撞见重名 / 同义节点当场合并，合并产物同样过守门。
- 关系边 token 的有界由查询渲染期按 `priority` 截断兜底（**关系侧不聚类**，聚类会坏归属语义）。

## 读写管线

MCS 的核心是两条管线，由 `MCS` 瘦门面分别委托给 `WritePipeline` 与 `QueryEngine`。

### 写入 `ingest`

```
input: str | IngestInput   (str → IngestInput(content=text)，now、无 source)
⓪ 规则入库       每次把整个输入记为一个事件节点（记录行为、落时间轴）+ 可选 source 切分；不经 LLM
① 前置插件链     WRITE_PREPROCESS（幂等检查等），只作用于 content
② 关联节点提取   复用 read 检索图中已有相关节点
③ 概念提取       仅 content：extract_concepts 抽概念 / 事实（带已有节点对齐）
④ 关系判定       judge_relations：合并同义、判关联 / 互斥 → DecisionList
⑤ 图更新 + 背书   命题 —关联— 端点；事件 / source —单向→ 本次概念 / 事实 背书；事实 —互斥— 事实；仅孤儿挂 __seed_root__
⑥ 主动守门 + 整窗单次裂变 + 边吸收   全局任意节点
⑦ persist       增量落盘；事件 / source 即使 content 抽空也随此落盘（记录行为已发生）
OUTPUT: 图状态更新 + 已持久化
```

⓪ 规则入库由内部原语 `_build_event_node` / `_build_source_nodes`（建节点）+ `_connect_endorsement_edges`
（连背书边）实现，**不经 LLM**。事件 / source **只能经统一 `ingest` 产生**——无独立的公开 `ingest_event` /
`ingest_source` 入口，背书目标固定为本次 `ingest` 抽出的概念 / 事实（非调用方指定）。

### 查询 `query`

```
input: query, [existing_context]
① 种子定位      jieba 切词 + 字面匹配名 / 别名为主力，embedding 兜底，root 仅最后退路
② 核心 BFS      沿关联边逐跳，每节点渲染活跃双向视图，LLM 选相关命题 / 邻居、端点补入（事件默认不进）
③ read-repair   读时收敛重名 / 同义
④ 后处理        重排 / 裁剪（postprocess 插件链）
OUTPUT: Subgraph（nodes + 选中的关联 / 互斥 edges）
```

写入复用读流程做"关联节点提取"——这是读写对称性的体现。

## 插件体系

MCS 采用模块式架构：核心引擎稳定，功能由插件链组合。统一基类 `mcs/core/plugin.py`（`Plugin` +
`PluginType`），各接口继承它；`PluginManager` 按 `PluginType` 索引，多接口插件经 `get_types()` 登记到每个类型。

**双 PluginManager**：`MCS` 持 `write_manager` 与 `read_manager` 两套，写入侧 / 读取侧插件分离注册，
可用不同 LLM 后端（`write_llm` / `read_llm`）。

14 类 `PluginType`（逐类签名与内置实现见 [plugin-system.md](plugin-system.md)）：

`ENTRY`、`TRIM`、`ARBITRATION`、`WRITE_PREPROCESS`、`QUERY_PREPROCESS`、`POSTPROCESS`、`COMPACTION`、
`INDEX`、`LLM`、`NODE_EXTENSION`、`EDGE_EXTENSION`、`STORAGE_SCHEMA_EXT`、`MAINTENANCE`、`SEED_SELECTOR`。

> `PREPROCESS` 与 `SEED_SELECTOR` 是**已废弃别名**：`PREPROCESS` 指向 `WRITE_PREPROCESS`；语义筛选已并入
> `TrimPlugin` 实现。二者保留一个版本后移除。

### 扩展模型（点 / 边对称）

节点与边都持 `extensions: dict` 槽位，插件经对称接口向其挂字段：

- **节点扩展** `NodeExtensionInterface`（`NODE_EXTENSION`）→ `Node.extensions`，经 `nodes.extensions_json` 持久化。
- **边扩展** `EdgeExtensionInterface`（`EDGE_EXTENSION`，与节点镜像）→ `Edge.extensions`，经 `edges.extensions_json`
  持久化；逐条随边保真存取、两端反查返回同一带扩展对象、重组 / 快照保真复制。未挂边扩展时行为逐字不变。

**字段级渲染可见性**：扩展自行决定在某 `purpose` 下是否渲染——`render(node/edge, purpose)` 返回片段=可见、
返回 `None`=隐藏。该可见性仅约束**渲染侧**；守门（铁律一）只估算节点层级视图、不渲染 / 不估算关系边。

**派生优先级**：`Edge.priority` 的目标态为派生值——由 `PriorityScorer` 从边扩展字段算、非写入方权威原语。
Phase 1 仅留默认 `0.0`（`edges.priority` 列作 Phase 2 派生缓存）。

## 存储

`StoreInterface`（`mcs/core/store.py`）是统一存储抽象，两个实现：`InMemoryStore`（无持久化）与
`SQLiteStore`（默认，`auto_persist=True` 时每次 `ingest()` 后增量落盘，`build()` 时自动加载已有库）。

SQLite 库记录建库出处（provenance）写入 `meta` 表：`schema_version`、已挂扩展名集等。打开已存在库时在任何
读写前校验 + 补列——扩展名集变化仅记 WARNING 放行（合法迁移），缺列则 `ALTER TABLE` 补齐。

## 目录结构

```
mcs/                             # 核心库（纯库，不含应用代码）
├── entities/                    # 纯数据模型（dataclass + 登记常量）
│   ├── graph.py                 # Node / Edge / Subgraph + node_class / 边类型常量
│   ├── decisions.py             # ConceptDraft / Decision / Community / MultiHubDecision / EventData / SourceData
│   └── config.py                # MCSConfig + PHASE1_* 常量
├── core/                        # 核心引擎
│   ├── plugin.py                # Plugin 基类 + PluginType 枚举
│   ├── store.py                 # StoreInterface（统一存储抽象）
│   ├── mcs.py                   # MCS 顶层瘦门面（ingest / query / 维护 / 插件注册）
│   ├── builder.py               # MCSBuilder 抽象
│   ├── write_pipeline.py        # WritePipeline + WriteContext
│   ├── query_engine.py          # QueryEngine + 种子定位 / BFS / get_related_events
│   ├── context_renderer.py      # ContextRenderer（按 purpose 渲染；估算 == 渲染口径）
│   ├── token_budget.py          # TokenBudget
│   ├── plugin_manager.py        # PluginManager（按 PluginType 索引）
│   └── errors.py                # 异常类型
├── interfaces/                  # 插件接口（ABC，每个 PluginType 一份）
├── plugins/                     # 插件实现（按目录分组）
│   ├── entry/                   # HubFallback（ENTRY）
│   ├── index/                   # AliasIndex（INDEX）+ AliasEntry（ENTRY）
│   ├── trim/                    # PriorityTrim、SemanticTrim（TRIM）
│   ├── preprocess/              # SourceTracking、IdempotencyCheck
│   ├── postprocess/             # Summary（NODE_EXTENSION）、Rerank（POSTPROCESS）
│   ├── maintenance/             # FanoutReducer / SummaryRegen / GraphSummary（COMPACTION / MAINTENANCE）
│   └── llm/                     # DeepSeek / Claude / Ollama（LLM）
├── stores/                      # in_memory.py / sqlite_store.py
├── presets/                     # phase1.py（Phase1Builder / create_mcs / 默认插件注册表）
├── prompts/                     # 各 purpose 默认 prompt
├── rendering.py                 # 共享结果渲染纯函数（供 mcs_mcp / mcs_agent 复用）
├── diagnostics/                 # 诊断 / 观测辅助
└── utils/                       # 工具函数
```

应用包与 `mcs/` 平级：

```
mcs_mcp/      # MCP（stdio）server 应用包 —— 把 MCS 作为 MCP 工具暴露（见 mcp-server.md）
mcs_agent/    # 记忆 agent 应用包 —— ReAct loop + FastAPI + 前端可视化（见 memory-agent.md）
bench/        # 评测框架（multihop_rag / extraction_quality，见 evaluation.md）
examples/     # 使用示例（basic_usage.py / wiki_example.py）
docs/         # 理解性文档（本文件所在目录）
openspec/     # 规范（specs/，L3 契约）与变更管理（changes/）
tests/        # 测试套件
```

## 依赖

- Python 3.10+
- SQLite（内置）
- LLM API：DeepSeek（默认）/ Claude / Ollama，三选一按需安装
- 可选：`mcp`（MCP server）、`PyYAML`（YAML 配置）—— 核心库不强依赖，惰性导入

## 进一步阅读

- [graph-model-design.md](graph-model-design.md) — 完整、权威的图模型与核心算法设计
- [getting-started.md](getting-started.md) — 5 分钟上手
- [plugin-system.md](plugin-system.md) — 14 类插件逐一说明 + 自定义插件开发
- [api-reference.md](api-reference.md) — 公开方法 / 数据类 / Builder / MCP 工具
- [Spec 索引](../openspec/specs/INDEX.md) — 按能力域分组的契约规范

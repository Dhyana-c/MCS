# MCS 架构总览

> 本文档是 MCS 的理解性文档，解释"为什么"和"怎么理解"。具体的契约定义见 `openspec/specs/` 下的 capability spec。

## 系统定位

MCS（Maximum-Context Subgraph）是**可扩展的记忆系统**——面向单一领域，由大模型语义驱动，把零散文本组织成图结构的语义记忆。

MCS 不依赖 embedding / 向量检索，靠大模型直接阅读"装得下的局部子图"完成关系发现、聚类与召回。核心赌注是：**知识有足够的局部性**——回答一个问题所需要的概念，在图里彼此靠近，几跳语义游走就能连到一起。

MCS 默认返回相关节点集合（`List[Node]`），不是自然语言答案。它专注于"记忆本身"，把合成答案、多轮对话、追问加深等留给上层（RAG / Agent / Chatbot）。

## 双层结构

MCS 采用双层结构组织知识：

- **概念层（Concept Layer）**：从事实中提炼的语义网络，MCS 主体。一般有向图，允许环。这是检索和导航的主要结构。
- **事实层（Event Layer）**：原始事实的线性时序日志，只追加不修改（Phase 2 实现）。概念层是当前物化视图，可通过重放找回。

Phase 1 只实现概念层；Phase 2 通过追加插件（事件层、版本链、GC）切换到记忆系统模式，不替换核心引擎。

## 核心不变量

MCS 维持一条硬不变量：**任意节点 + 它的全部一跳子节点，渲染成 LLM 输入的 token 数 ≤ 一个上下文窗口 T**。

> **关系表示可插拔**（`relation_model`，默认 `property_graph`）：活跃视图的"关系边"组成随
> 模式切换——`property_graph` 为带 label 事实边、`attribute_node` 为无类型关联边 + 属性节点。
> 估算==渲染口径在每种模式内逐字成立；默认 `property_graph` 行为逐字不变。详见
> `attribute-node-model`。

这是导航、归纳、查询的共同地基。为什么需要这条不变量？

- LLM 的上下文窗口有限。如果某节点的一跳邻域超过 T，LLM 无法一次性"读完"邻居来做判断（聚类、导航、归纳），系统就失去了语义引擎的基础。
- 不变量保证：无论图如何增长，任意节点的"局部视野"（它 + 一跳子节点）永远放得进一个上下文窗口。

关键实现要点：
- **估算口径 == 渲染口径**：判断"邻域是否超 T"的估算，必须与 `context_renderer` 实际渲染逐字一致（含 name==content 去重）。用更少字段低估会漏判、直接破坏不变量。
- **一进多出聚类**：`decide_hub` 一次产出多个语义内聚的社区，每个社区按"合并同义 / 找关键概念 / 概括新概念"重组。
- **hub 复用**：若某节点的一跳子节点 ⊇ 某 hub 的全部成员，改连该 hub（减边、复用结构）。
- **禁止空洞聚合标签**：如"信息碎片集合""综合信息枢纽"。

## 边的方向

全图只有**单向边** `source → target`。语义关系以**两条对向单向边**（`a→b` 与 `b→a`）表达，保持双向可达性；层级关系为**纯下行单向边** `父→子`（无成员上行边）。

> **`relation_model` 双模式**：上述为默认 `property_graph` 模式的边语义。`attribute_node` 模式下，
> 关系改由**无类型关联边** `kind="assoc"`（无 label）+ **属性节点**（`role="attribute"`，content
> 持关系说法）表达；属性节点经 assoc 连两端、不进层级骨架、不参与 fanout 收敛。详见
> `attribute-node-model`。

为什么不这样做？

- 单向边 + 方向语义清晰：导航沿出边自顶向下下钻，避免缠绕成环。
- 语义边双向表达：概念间的关联本身是双向的（"深度学习"与"神经网络"互相关联），用两条对向单向边保持双向可达。
- 层级骨架由节点 `role`（`role=="hub"`）识别，不依赖边方向。

## 读写管线

MCS 的核心是两条对称管线：

### 写入管线（Ingest）— 7 段

```
input: text
① 前置插件链 (可选)
② 关联节点定位 ◄─ 复用读流程
③ 概念提取 (LLM)
④ 关系判定 (LLM) → DecisionList
⑤ 图更新 (无 LLM)
⑥ 压缩判定插件链 (条件触发)
⑦ 自动落盘 (StorageInterface 增量持久化)
OUTPUT: 图状态更新 + 已持久化
```

写入流程复用读流程做关联节点定位——这是读写对称性的体现。

### 查询管线（Query）— 5 段

```
input: query, [ctx]
① 前置插件链 (可选)
② 种子定位 (入口插件链+裁剪)
③ 语义理解 Loop (BFS + visited + 上限)
④ 仲裁 (≤1, 单一职责)
⑤ 后置处理链 (0..N, 串联)
OUTPUT: List[Node]
```

详细流程说明见 [core-flows.md](core-flows.md)。

## 插件体系

MCS 采用模块式架构：核心引擎稳定不变，功能通过插件链组合。

插件统一基类 `core/plugin.py`（`Plugin` + `PluginType`），各接口继承它。`PluginManager` 按 `PluginType` 索引，多接口插件经 `get_types()` 登记到每个类型。

### 插件类型

| 类型 | 关注 | Phase 1 实现 |
|------|------|-------------|
| ENTRY | 种子定位入口 | AliasEntry, HubFallback |
| TRIM | 候选集裁剪 | PriorityTrim |
| ARBITRATION | 结果仲裁 | — |
| WRITE_PREPROCESS | 写入前置 | IdempotencyCheck |
| QUERY_PREPROCESS | 查询前置 | — |
| POSTPROCESS | 后置处理 | DocRerank |
| COMPACTION | 压缩/扇出控制 | FanoutReducer, SummaryRegen |
| INDEX | 索引构建 | AliasIndex |
| LLM | LLM 适配 | DeepSeek, Claude, Ollama |
| NODE_EXTENSION | 节点扩展 | SourceTracking |
| EDGE_EXTENSION | 边扩展 | —（opt-in，Phase 2 字段） |
| STORAGE_SCHEMA_EXT | 存储扩展 | — |
| MAINTENANCE | 维护操作 | — |
| SEED_SELECTOR | 种子选择 | — |

### 扩展模型（点 / 边对称）

节点与边都持 `extensions: dict` 槽位，插件经对称接口向其挂字段：

- **节点扩展**：`NodeExtensionInterface`（`PluginType.NODE_EXTENSION`）→ `Node.extensions`；经 `nodes.extensions_json` 持久化。
- **边扩展**：`EdgeExtensionInterface`（`PluginType.EDGE_EXTENSION`，与节点镜像）→ `Edge.extensions`；经 `edges.extensions_json` 持久化，与节点同构地保真编解码（`serialize`/`deserialize`）、**两端反查**（`get_facts`/`get_assoc`）返回的同一对象带完整扩展、**重组**（fanout `_migrate_edges`）与**快照 / 回滚**保真复制（独立 dict、不共享引用）。未挂边扩展时行为逐字不变。

**字段级渲染可见性**：每个扩展自行决定在某 `purpose` 下是否渲染——`render(node/edge, purpose)` 返回片段=可见、返回 `None`=隐藏、不进渲染文本（点 / 边共用同一判定规则）。边渲染函数 `render_fact_edge` / `render_assoc_edge` 带 `purpose` 参以支持按 purpose 切换；`render_facts` 透传自身 `purpose`。该可见性仅约束**渲染侧**；守门（铁律一）只估算节点层级视图、不渲染 / 不估算关系边，**不受影响**。

**边渲染 / 估算的查询侧一致性**：`estimate_fact_edge` / `estimate_assoc_edge` 委托对应 `render_*_edge` 取文本后估算（**不另开估算公式**），随渲染签名透传 `extensions` / `purpose`，使可见扩展片段在两侧一致。此一致性服务**查询侧** token 计数正确性（`render_facts` 渲染事实给 LLM 的真实窗口；及 Phase 2 对查询视图按 `priority` 截断），与守门铁律一无关。

**派生优先级（seam）**：`Edge.priority` 的目标态为派生值——由 `PriorityScorer` 从边扩展字段（创建时间、活跃数等 Phase 2 字段）算、非写入方权威原语。Phase 1 仅引入 seam：`DefaultPriorityScorer` 返回 `0.0`（零行为变化），store 层 chokepoint（`Edge` 创建处）持有但**不调用**、不在写路径接 scorer；`edges.priority` 列作 Phase 2 派生值缓存保留。真实打分与写路径接线留 Phase 2。

### 存储出处（provenance）

持久化库（`SQLiteStore`）记录建库出处：`relation_model`、`schema_version`、已挂扩展名集（点 + 边扩展 `get_name()` 排序序列化），写入 `meta` 表。打开已存在库时**在任何读写前**校验 + 补列：

- `relation_model` 不一致 → **拒绝**打开（抛 `StoreProvenanceError`，防混库静默损坏；唯一硬拒条件）。
- 扩展名集变化 → 仅记 WARNING、放行（合法迁移：新字段取默认、旧 orphan 字段被忽略）。
- 出处缺失（旧库无 `meta`）→ 视为 legacy，按当前配置补写 + WARNING 放行。
- 旧库缺 `edges.extensions_json` 列 → `ALTER TABLE edges ADD COLUMN` 补齐（`CREATE TABLE IF NOT EXISTS` 对既存表是 no-op、不加列；不补会让放行后的库 INSERT 即抛 `OperationalError`）。

`InMemoryStore` 无持久化，provenance / 补列均 no-op。

### Phase 1 vs Phase 2

Phase 1（知识图谱模式）与 Phase 2（记忆系统模式）通过追加插件切换，互不替换：

| | 知识图谱模式 (Phase 1) | 记忆系统模式 (Phase 2，规划中) |
|---|---|---|
| 场景 | Wiki / 企业知识库 | 对话记忆 / 事件追踪 |
| 入口插件 | AliasEntry + HubFallback | + TimeSeriesEntry |
| 仲裁 | 无 | LLMArbitration |
| 压缩链 | FanoutReducer + SummaryRegen | + EventLayer / Versioning / GC |

## 目录结构

```
mcs/
├── entities/                   # 纯数据模型（dataclass + 常量）
│   ├── graph.py                # Node, Edge, Subgraph
│   ├── decisions.py            # ConceptDraft, Decision, Community, MultiHubDecision
│   └── config.py               # MCSConfig + PHASE1_* 常量
│
├── core/                       # 核心引擎（服务/契约/异常/值对象）
│   ├── token_budget.py         # TokenBudget
│   ├── context_renderer.py     # ContextRenderer (按 purpose 渲染)
│   ├── write_pipeline.py       # WritePipeline (7 段) + WriteContext + DecisionList
│   ├── query_engine.py         # QueryEngine (5 段) + QueryContext
│   └── plugin_manager.py       # PluginManager
│
├── interfaces/                 # 插件接口（ABC）
│   ├── storage.py              # StorageInterface
│   ├── index.py                # IndexInterface
│   ├── llm.py                  # LLMInterface
│   ├── node_extension.py       # NodeExtensionInterface
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
│   └── phase2/                 # Phase 2 插件（预留）
│
├── presets/                    # 预设配置
│   ├── __init__.py             # create_mcs() 便捷函数
│   └── phase1.py               # Phase1Builder
│
├── prompts/                    # 9 个 purpose 的默认 prompt
└── utils/                      # 工具函数
```

其他顶层目录：

```
docs/               # 理解性文档（本文件所在目录）
openspec/           # 规范与变更管理
  ├── specs/        # Capability specs (L3)
  └── changes/      # 变更提案与归档
bench/              # 评测框架
tests/              # 测试套件
examples/           # 使用示例
scripts/            # 工具脚本
```

## 依赖

- Python 3.10+
- SQLite（内置）
- LLM API：DeepSeek / Claude / Ollama（三选一，按需安装）

## 进一步阅读

- [核心流程](core-flows.md) — 读写管线的详细说明
- [技术方案](technical-design.md) — 完整的机制设计文档
- [Spec 索引](../openspec/specs/INDEX.md) — 按能力域分组的契约规范

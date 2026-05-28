---
name: mcs-architecture
description: MCS 模块式架构设计，核心引擎 + 插件系统
metadata:
  type: architecture
  version: 2.0
  phase: 1
---

# MCS 模块式架构设计

## 1. 架构概述

### 1.1 设计目标

MCS（Maximum-Context Subgraph）采用**核心稳定 + 数据可扩展 + 流程严格**的模块式架构：

- **核心引擎**：最小、稳定的图操作骨架；Node 只保留身份字段，所有可变字段走 `extensions` 字典
- **数据扩展**：`aliases / summary / sources / versions / confidence ...` 等字段全部通过 `node.extensions[plugin_name]` 由插件挂载和管理
- **流程契约**：写入和查询流程定义为显式**状态机**，每个状态点暴露 hook 钩子；插件通过实现 hook 接口介入流程
- **两期共存**：第一期（知识图谱）与第二期（记忆系统）通过插件配置切换，**核心引擎完全不变**

### 1.2 整体架构图

```
┌─────────────────────────────────────────────────────────────────────────────┐
│                              MCS 整体架构                                    │
├─────────────────────────────────────────────────────────────────────────────┤
│                                                                             │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │                       应用层 (Application Layer)                    │   │
│   │       CLI Tool   |   REST API (FastAPI)   |   Python SDK            │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
│                                  │                                          │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │                       配置层 (MCSConfig)                            │   │
│   │   mode | token_budget | plugins[] | plugin_configs                  │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
│                                  │                                          │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │                  插件管理器 (PluginManager)                          │   │
│   │   register | get | get_all | collect_schema_extensions              │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
│                                  │                                          │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │                       核心引擎 (Core Engine)                        │   │
│   │                                                                     │   │
│   │   ┌──────────────────────  数据结构层  ────────────────────────┐    │   │
│   │   │  GraphStore  |  Node (最小核心 + extensions)  |  Edge       │    │   │
│   │   │  TokenBudget  |  Serializer  |  HookContext / QueryContext  │    │   │
│   │   └─────────────────────────────────────────────────────────────┘    │   │
│   │                                                                     │   │
│   │   ┌──────────────────────  处理管线层  ────────────────────────┐    │   │
│   │   │   WritePipeline (9 状态点)  |  QueryEngine (7 状态点)       │    │   │
│   │   └─────────────────────────────────────────────────────────────┘    │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
│                                  │ 依赖接口                                 │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │                       接口层 (Interfaces)                           │   │
│   │   Storage | Index | LLM | NodeExtension | PipelineHook              │   │
│   │   QueryHook | StorageSchemaExtension | Maintenance                  │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
│                                  │ 实现接口                                 │
│   ┌─────────────────────────────────────────────────────────────────────┐   │
│   │                       插件层 (Plugins)                              │   │
│   │                                                                     │   │
│   │   第一期 (5 个)：                                                   │   │
│   │     AliasIndexPlugin  ─ Index + NodeExt(aliases) + PipelineHook    │   │
│   │     SummaryPlugin     ─ NodeExt(summary) + PipelineHook            │   │
│   │     SourceTracking    ─ NodeExt(sources) + PipelineHook + SchemaExt│   │
│   │     SQLiteStorage     ─ Storage                                    │   │
│   │     DeepSeekLLM       ─ LLM                                        │   │
│   │                                                                     │   │
│   │   第二期 (叠加)：                                                   │   │
│   │     EventLayer | Versioning | Confidence | TimeSeriesEntry         │   │
│   │     GC | Arbitration                                               │   │
│   │                                                                     │   │
│   └─────────────────────────────────────────────────────────────────────┘   │
│                                                                             │
└─────────────────────────────────────────────────────────────────────────────┘
```

### 1.3 写入管线状态机

```
ingest(text, **metadata)
    │
    ▼
┌──────────────────┐
│ INGEST_START     │ ◄── 幂等检查、ctx.skip 短路 (e.g. SourceTracking)
└──────────────────┘
    │
    ▼ LLM.extract_concepts(text)
┌──────────────────┐
│ EXTRACTED        │ ◄── 别名生成 (e.g. AliasIndex)、概念过滤
└──────────────────┘
    │
    ▼ for each concept: place(concept)
┌──────────────────┐
│ PLACE_START      │
└──────────────────┘
    │
    ▼ self._find_anchors(concept)
┌──────────────────┐
│ ANCHORS_FOUND    │ ◄── 锚点过滤、同名消歧（Phase 2）
└──────────────────┘
    │
    ▼ LLM.check_exists(concept, subgraph)
┌──────────────────┐
│ EXISTENCE_CHECKED│
└──────────────────┘
    │
    ▼ create_or_merge → ctx.node
┌──────────────────┐
│ CREATED_OR_MERGED│ ◄── 挂数据到 node.extensions
│                  │     (Summary 生成、SourceTracking 追加 source)
└──────────────────┘
    │
    ▼ self._check_fanout(ctx.node)
┌──────────────────┐
│ FANOUT_CHECKED   │ ◄── 触发降扇出 / 社区合并
└──────────────────┘
    │
    ▼
┌──────────────────┐
│ PLACE_END        │
└──────────────────┘
    │
    ▼ (循环至下个 concept)
┌──────────────────┐
│ INGEST_END       │ ◄── 登记 chunk (SourceTracking)
└──────────────────┘
```

### 1.4 查询引擎状态机

```
query(query_text, max_tokens)
    │
    ▼
┌──────────────────┐
│ QUERY_START      │
└──────────────────┘
    │
    ▼ self._locate_seeds(query) [词法 + 时序兜底]
┌──────────────────┐
│ SEEDS_LOCATED    │ ◄── 种子过滤/扩展 (TimeSeriesEntry、消歧)
└──────────────────┘
    │
    ▼
┌──────────────────┐
│ TRAVERSE_START   │
└──────────────────┘
    │
    ▼ 循环遍历前沿
┌──────────────────┐
│ TRAVERSE_STEP    │ ◄── 每访问一节点触发一次
└──────────────────┘
    │
    ▼ (前沿空 / token 上限)
┌──────────────────┐
│ TRAVERSE_END     │
└──────────────────┘
    │
    ▼
┌──────────────────┐
│ SYNTHESIZE_START │ ◄── 仲裁、版本筛选 (Arbitration)
└──────────────────┘
    │
    ▼ LLM.synthesize(query, accumulated)
┌──────────────────┐
│ QUERY_END        │ ◄── 答案返回前的后处理
└──────────────────┘
```

### 1.5 插件交互图

```
┌─────────────────────────────────────────────────────────────────────────┐
│                          核心引擎调用插件                                │
│                                                                         │
│   WritePipeline                                                         │
│   ────────────                                                          │
│       ├──► LLM.extract_concepts() / check_exists() / decide_hub()       │
│       ├──► Index.lookup()                                ← AliasIndex   │
│       ├──► emit(state, ctx)  ── 触发 9 个状态点                         │
│       │       ├─ on_ingest_start         ← SourceTracking (幂等检查)    │
│       │       ├─ on_extracted            ← AliasIndex (生成 aliases)    │
│       │       ├─ on_anchors_found        ← (Phase 2: 消歧)              │
│       │       ├─ on_created_or_merged    ← Summary (生成摘要)           │
│       │       │                          ← SourceTracking (追加 source) │
│       │       │                          ← AliasIndex (更新索引)        │
│       │       ├─ on_existence_checked    ← (Phase 2: 矛盾检测)          │
│       │       └─ on_ingest_end           ← SourceTracking (登记 chunk)  │
│       │                                                                 │
│   QueryEngine                                                           │
│   ───────────                                                           │
│       ├──► Index.lookup()                                ← AliasIndex   │
│       ├──► LLM.decide_directions() / synthesize()                       │
│       └──► emit(state, ctx)  ── 触发 7 个状态点                         │
│               ├─ on_seeds_located        ← (Phase 2: TimeSeries)        │
│               ├─ on_traverse_step        ← (可观测)                     │
│               └─ on_synthesize_start     ← (Phase 2: Arbitration)       │
│                                                                         │
│   GraphStore（初始化/关闭时）                                            │
│   ─────────                                                             │
│       ├──► Storage.initialize(schema_extensions)                        │
│       │       └─ 收集所有 StorageSchemaExtension 的列定义和辅助表       │
│       ├──► Storage.save_node() / save_edge()                            │
│       └──► Storage.load()                                               │
│                                                                         │
└─────────────────────────────────────────────────────────────────────────┘
```

### 1.6 两期配置对比

```
┌─── 第一期：知识图谱模式 ────────────────────────────────────────────┐
│  config = MCSConfig.knowledge_graph()                              │
│  plugins = [                                                       │
│      "alias_index",      # IndexInterface + NodeExt + PipelineHook │
│      "summary",          # NodeExt + PipelineHook                  │
│      "source_tracking",  # NodeExt + PipelineHook + SchemaExt      │
│      "sqlite_storage",   # StorageInterface                        │
│      "deepseek_llm",     # LLMInterface                            │
│  ]                                                                 │
│  特点：静态知识、教科书/Wiki 场景、不处理时序冲突                  │
└─────────────────────────────────────────────────────────────────────┘

┌─── 第二期：记忆系统模式 ────────────────────────────────────────────┐
│  config = MCSConfig.memory_system()                                │
│  plugins = [                                                       │
│      # 继承 Phase 1 全部 5 个插件                                  │
│      "alias_index", "summary", "source_tracking",                  │
│      "sqlite_storage", "deepseek_llm",                             │
│      # Phase 2 叠加                                                │
│      "event_layer",       # StorageInterface + PipelineHook        │
│      "versioning",        # NodeExt + PipelineHook                 │
│      "confidence",        # NodeExt + PipelineHook                 │
│      "timeseries_entry",  # QueryHook                              │
│      "gc",                # MaintenanceInterface                   │
│      "arbitration",       # QueryHook                              │
│  ]                                                                 │
│  特点：动态/时序知识、对话记忆、矛盾仲裁                            │
└─────────────────────────────────────────────────────────────────────┘

         核心引擎完全不变，通过插件配置切换产品形态
```

### 1.7 架构层次简图

```
┌───────────────────────────────────────────────────────────────┐
│  配置层      MCSConfig（mode、plugins、plugin_configs）        │
├───────────────────────────────────────────────────────────────┤
│  插件管理    PluginManager（注册、查找、schema 收集）          │
├───────────────────────────────────────────────────────────────┤
│  核心引擎    GraphStore | TokenBudget | Serializer            │
│              WritePipeline (9 状态点) | QueryEngine (7 状态点)│
├───────────────────────────────────────────────────────────────┤
│  接口层      Storage | Index | LLM | NodeExtension            │
│              PipelineHook | QueryHook                         │
│              StorageSchemaExtension | Maintenance             │
├───────────────────────────────────────────────────────────────┤
│  插件层      Phase 1 (5): AliasIndex, Summary, SourceTracking,│
│                           SQLiteStorage, DeepSeekLLM          │
│              Phase 2 (6): EventLayer, Versioning, Confidence, │
│                           TimeSeriesEntry, GC, Arbitration    │
└───────────────────────────────────────────────────────────────┘
```

### 1.8 依赖原则

- **依赖倒置**：核心引擎依赖接口，插件实现接口
- **核心无依赖**：核心引擎不依赖任何具体插件实现
- **数据开放扩展**：Node 字段固定，可变数据全部走 `extensions`
- **流程封闭修改**：状态点固定（9 + 7），新行为通过新增 hook 接入，不改流程主干
- **插件可替换**：同类插件可互换（如更换 LLM 插件）

---

## 2. 核心引擎

### 2.1 GraphCore - 图结构核心（最小核心）

**职责**：图数据结构的基础操作，不涉及任何语义判断或可变字段。

```python
class Node:
    """概念节点（最小核心）

    所有可变 / 场景相关字段（aliases、summary、sources、versions、confidence ...）
    全部通过 extensions 由插件挂载和管理。
    """
    id: str                    # 唯一标识
    name: str                  # 规范名（去歧义化，如 "苹果(科技公司)"）
    content: str               # 完整描述
    role: str                  # "concept" | "hub" | "attribute"
    extensions: dict[str, Any] # 插件数据挂载点，key = 插件名


class Edge:
    """无类型邻接边"""
    source_id: str
    target_id: str
    direction: str             # "bidirectional" | "out"（合并后涌现）


class GraphStore:
    """图存储操作"""
    def add_node(node: Node) -> str
    def get_node(node_id: str) -> Node | None
    def update_node(node_id: str, updates: dict)
    def delete_node(node_id: str)

    def add_edge(source_id: str, target_id: str)
    def get_neighbors(node_id: str) -> list[Node]
    def get_edge(source_id: str, target_id: str) -> Edge | None
    def delete_edge(source_id: str, target_id: str)

    def get_subgraph(node_id: str, max_tokens: int) -> Subgraph
    def get_all_nodes() -> list[Node]
    def get_all_edges() -> list[Edge]
```

**Extensions 字典约定**：

```python
node.extensions = {
    "alias_index":     {"aliases": ["苹果", "Apple", "AAPL"]},
    "summary":         {"text": "...", "generated_at": datetime},
    "source_tracking": {"sources": [Source(...), ...]},
    # Phase 2:
    "versioning":      {"versions": [...]},
    "confidence":      {"score": 0.85, "last_confirmed_at": datetime},
}
```

- **key 命名规则**：固定使用插件的 `name` 属性，多插件共存清晰
- **隔离原则**：插件只读写自己 slot 的 key；跨插件读取需经显式接口（如 Serializer 通过 helper 函数访问）
- **缺失处理**：插件读取时若 slot 不存在，应用 `default()` 返回的默认值，不抛异常

**不变式**：一跳邻域 Token 总量 ≤ T（由 WritePipeline 保证）。

### 2.2 TokenBudget - Token 预算

```python
class TokenBudget:
    def __init__(self, max_tokens: int):
        self.T = max_tokens  # 预算上限，建议 W/2

    def estimate(text: str) -> int:
        """估算文本 Token 数（第一期简单估算；后续接 LLM 真实 tokenizer）"""
        pass

    def check_subgraph(nodes: list[Node]) -> bool:
        total = sum(self.estimate(n.content) for n in nodes)
        return total <= self.T

    def get_budget_for_merge() -> int:
        """合并时可用预算（两块各 T，合起来 2T = W）"""
        return self.T * 2
```

### 2.3 Serializer - 子图序列化

```python
class Serializer:
    def serialize(subgraph: Subgraph, mode: str = "full") -> str:
        """
        mode:
          - "navigation": 焦点 + 邻居 + 关键说法 + 结构提示
          - "full": 提纲 + 交叉引用 + 相关说法
        """
        pass

    @staticmethod
    def get_summary(node: Node) -> str:
        """读 extensions["summary"]["text"]，缺失则 fallback 到 content[:200]

        Serializer 通过此 helper 取摘要，而不直接访问 node 字段。
        SummaryPlugin 未启用时也能 graceful degrade。
        """
        ext = node.extensions.get("summary", {})
        return ext.get("text") or node.content[:200]
```

### 2.4 WritePipeline - 写入管线（状态机）

**职责**：概念的增量放置、合并、降扇出。流程定义为 9 个显式状态点，每个状态点触发 hook 回调，插件通过实现 `PipelineHookInterface` 介入。

```python
from enum import Enum
from dataclasses import dataclass, field

class WritePipelineState(Enum):
    INGEST_START       = "ingest_start"
    EXTRACTED          = "extracted"
    PLACE_START        = "place_start"
    ANCHORS_FOUND      = "anchors_found"
    EXISTENCE_CHECKED  = "existence_checked"
    CREATED_OR_MERGED  = "created_or_merged"
    FANOUT_CHECKED     = "fanout_checked"
    PLACE_END          = "place_end"
    INGEST_END         = "ingest_end"


@dataclass
class HookContext:
    """写入流程上下文，贯穿一次 ingest / place 调用"""
    text: str = None                       # ingest 输入文本
    concepts: list = None                  # extract_concepts 结果
    concept: object = None                 # 当前 place 的概念
    anchors: list = None                   # 找到的锚点节点
    exists: bool = None                    # 是否已存在
    existing_node: Node = None             # 匹配到的已有节点
    node: Node = None                      # 最终落到图里的节点
    skip: bool = False                     # 插件可设 True 短路流程
    metadata: dict = field(default_factory=dict)  # 自由 slot（doc_id 等放这）


class WritePipeline:
    def __init__(self, graph: GraphStore, llm: LLMInterface,
                 index: IndexInterface, hooks: list[PipelineHookInterface],
                 token_budget: TokenBudget):
        self.graph = graph
        self.llm = llm
        self.index = index            # 写入时找锚点用别名词典
        self.hooks = hooks
        self.token_budget = token_budget

    def _emit(self, state: WritePipelineState, ctx: HookContext):
        """触发某状态点的所有 hook"""
        method_name = f"on_{state.value}"
        for hook in self.hooks:
            getattr(hook, method_name, lambda c: None)(ctx)

    def ingest(self, text: str, **metadata):
        """摄入文本，抽取概念并放置

        metadata 自由字段（如 doc_id, chunk_id, section_title）由插件解读，
        核心不关心其内容。
        """
        ctx = HookContext(text=text, metadata=metadata)

        self._emit(WritePipelineState.INGEST_START, ctx)
        if ctx.skip:                       # 插件短路（如 SourceTracking 检出重复）
            return

        ctx.concepts = self.llm.extract_concepts(text)
        self._emit(WritePipelineState.EXTRACTED, ctx)
        # 插件可在此修改 ctx.concepts（如 AliasIndex 生成别名）

        for concept in ctx.concepts:
            self.place(concept, parent_ctx=ctx)

        self._emit(WritePipelineState.INGEST_END, ctx)

    def place(self, concept, parent_ctx: HookContext = None):
        """放置单个概念"""
        ctx = parent_ctx or HookContext(metadata={})
        ctx.concept = concept

        self._emit(WritePipelineState.PLACE_START, ctx)

        ctx.anchors = self._find_anchors(concept)
        self._emit(WritePipelineState.ANCHORS_FOUND, ctx)
        # 插件可在此修改 ctx.anchors（如 Phase 2 同名消歧）

        if ctx.anchors:
            subgraph = self.graph.get_subgraph(ctx.anchors[0].id, self.token_budget.T)
            ctx.exists, ctx.existing_node = self.llm.check_exists(concept, subgraph)
        else:
            ctx.exists, ctx.existing_node = self._navigate_from_root(concept)
        self._emit(WritePipelineState.EXISTENCE_CHECKED, ctx)

        if ctx.exists:
            self._merge_into(concept, ctx.existing_node)
            ctx.node = ctx.existing_node
        else:
            ctx.node = self._create_node(concept)
            self._connect_to_anchors(ctx.node, ctx.anchors)
        self._emit(WritePipelineState.CREATED_OR_MERGED, ctx)
        # 插件在此挂数据到 ctx.node.extensions
        # (Summary 生成摘要、SourceTracking 追加 source、AliasIndex 更新索引)

        self._check_fanout(ctx.node)
        self._emit(WritePipelineState.FANOUT_CHECKED, ctx)

        self._emit(WritePipelineState.PLACE_END, ctx)
        return ctx.node

    def merge_community(self, hub_id: str):
        """合并社区，塌缩为星型（含义不变，也走 hook 通知）"""
        ...

    def reduce_fanout(self, node_id: str):
        """降扇出：提拔现有概念或造合成枢纽"""
        ...

    def _find_anchors(self, concept):
        """用 self.index.lookup() 查 concept.name + aliases，返回已在图中的共现概念"""
        candidates = set()
        candidates.update(self.index.lookup(concept.name))
        for alias in getattr(concept, "aliases", []):
            candidates.update(self.index.lookup(alias))
        return [self.graph.get_node(nid) for nid in candidates]
```

**状态点契约表**

| 状态 | 触发时机 | ctx 关键字段 | 插件可读 | 插件可写 |
|---|---|---|---|---|
| INGEST_START | ingest 调用入口 | text, metadata | 全部 | skip, metadata |
| EXTRACTED | concepts 抽出后 | concepts | concepts | concepts |
| PLACE_START | 单个 place 开始 | concept | concept | concept |
| ANCHORS_FOUND | 锚点找到后 | anchors | anchors | anchors（过滤） |
| EXISTENCE_CHECKED | 判断存在后 | exists, existing_node | 全部 | -（只读） |
| CREATED_OR_MERGED | 节点确定后 | node | node | node.extensions[slot] |
| FANOUT_CHECKED | 扇出检查后 | node | node | -（只读） |
| PLACE_END | place 结束 | node | 全部 | -（只读） |
| INGEST_END | ingest 结束 | concepts, ... | 全部 | metadata |

### 2.5 QueryEngine - 查询引擎（状态机）

**职责**：语义遍历，激活扩散。7 个状态点，对应钩子接口 `QueryHookInterface`。

```python
class QueryPipelineState(Enum):
    QUERY_START      = "query_start"
    SEEDS_LOCATED    = "seeds_located"
    TRAVERSE_START   = "traverse_start"
    TRAVERSE_STEP    = "traverse_step"
    TRAVERSE_END     = "traverse_end"
    SYNTHESIZE_START = "synthesize_start"
    QUERY_END        = "query_end"


@dataclass
class QueryContext:
    query: str
    seeds: list[Node] = None
    current_node: Node = None             # 当前 TRAVERSE_STEP 访问的节点
    accumulated: list[Node] = None
    answer: str = None
    metadata: dict = field(default_factory=dict)


class QueryEngine:
    def __init__(self, graph: GraphStore, llm: LLMInterface,
                 index: IndexInterface, hooks: list[QueryHookInterface],
                 token_budget: TokenBudget):
        self.graph = graph
        self.llm = llm
        self.index = index
        self.hooks = hooks
        self.token_budget = token_budget

    def _emit(self, state: QueryPipelineState, ctx: QueryContext):
        method_name = f"on_{state.value}"
        for hook in self.hooks:
            getattr(hook, method_name, lambda c: None)(ctx)

    def query(self, query: str, max_tokens: int = None) -> str:
        ctx = QueryContext(query=query)

        self._emit(QueryPipelineState.QUERY_START, ctx)

        ctx.seeds = self._locate_seeds(query)
        self._emit(QueryPipelineState.SEEDS_LOCATED, ctx)
        # 插件可在此扩展/过滤 ctx.seeds（Phase 2 TimeSeriesEntry / 消歧）

        self._emit(QueryPipelineState.TRAVERSE_START, ctx)
        ctx.accumulated = self._traverse(ctx, max_tokens)
        self._emit(QueryPipelineState.TRAVERSE_END, ctx)

        self._emit(QueryPipelineState.SYNTHESIZE_START, ctx)
        # 插件可在此对 ctx.accumulated 做仲裁（Phase 2 Arbitration）

        ctx.answer = self._synthesize(query, ctx.accumulated)
        self._emit(QueryPipelineState.QUERY_END, ctx)

        return ctx.answer

    def _locate_seeds(self, query: str) -> list[Node]:
        """词法入口为主，命中失败时顶点兜底"""
        node_ids = self.index.lookup(query)
        if node_ids:
            return [self.graph.get_node(nid) for nid in node_ids]
        return self._navigate_from_root(query)

    def _traverse(self, ctx: QueryContext, max_tokens: int) -> list[Node]:
        visited, frontier, accumulated = set(), ctx.seeds, []
        while frontier and self._estimate_tokens(accumulated) < max_tokens:
            next_frontier = []
            for node in frontier:
                if node.id in visited: continue
                visited.add(node.id)
                ctx.current_node = node

                subgraph = self.graph.get_subgraph(node.id, self.token_budget.T)
                serialized = Serializer().serialize(subgraph, mode="navigation")
                directions = self.llm.decide_directions(
                    ctx.query, node, serialized, accumulated
                )
                neighbors = self.graph.get_neighbors(node.id)
                for n in neighbors:
                    if n.id in directions:
                        accumulated.append(n)
                        next_frontier.append(n)

                self._emit(QueryPipelineState.TRAVERSE_STEP, ctx)
            frontier = next_frontier
        return accumulated

    def _synthesize(self, query: str, nodes: list[Node]) -> str:
        content = Serializer().serialize_nodes(nodes, mode="full")
        return self.llm.synthesize(query, content)
```

**状态点契约表**

| 状态 | 触发时机 | ctx 关键字段 | 插件可读 | 插件可写 |
|---|---|---|---|---|
| QUERY_START | query 调用入口 | query | query | metadata |
| SEEDS_LOCATED | seeds 定位后 | seeds | seeds | seeds（扩展/过滤） |
| TRAVERSE_START | 遍历开始前 | seeds | seeds | -（只读） |
| TRAVERSE_STEP | 每访问一节点后 | current_node, accumulated | current_node, accumulated | accumulated |
| TRAVERSE_END | 遍历结束 | accumulated | accumulated | accumulated |
| SYNTHESIZE_START | 合成前 | accumulated | accumulated | accumulated（仲裁） |
| QUERY_END | query 结束 | answer | 全部 | -（只读） |

---

## 3. 接口定义

### 3.1 StorageInterface - 存储接口

```python
class StorageInterface(ABC):
    @abstractmethod
    def initialize(self, schema_extensions: list["StorageSchemaExtensionInterface"]):
        """初始化时收集所有 schema 扩展，动态构建表结构"""
        pass

    @abstractmethod
    def save(self, graph: GraphStore): pass

    @abstractmethod
    def load(self) -> GraphStore: pass

    @abstractmethod
    def save_node(self, node: Node): pass

    @abstractmethod
    def save_edge(self, edge: Edge): pass
```

### 3.2 IndexInterface - 索引接口

```python
class IndexInterface(ABC):
    @abstractmethod
    def build(self, graph: GraphStore): pass

    @abstractmethod
    def lookup(self, query: str) -> list[str]:
        """返回命中的节点 ID 列表"""
        pass

    @abstractmethod
    def add_entry(self, node: Node): pass

    @abstractmethod
    def remove_entry(self, node_id: str): pass

    @abstractmethod
    def update_entry(self, node: Node): pass
```

### 3.3 LLMInterface - LLM 接口

```python
class LLMInterface(ABC):
    @abstractmethod
    def call(self, prompt: str, system: str = None) -> str: pass

    # 流程相关
    @abstractmethod
    def extract_concepts(self, text: str) -> list[Concept]: pass

    @abstractmethod
    def check_exists(self, concept, subgraph: str) -> tuple[bool, Node | None]: pass

    @abstractmethod
    def decide_hub(self, subgraph: str) -> HubDecision: pass

    @abstractmethod
    def decide_directions(self, query, current_node, subgraph,
                          accumulated) -> list[str]: pass

    @abstractmethod
    def synthesize(self, query: str, content: str) -> str: pass

    # 插件辅助方法（由 AliasIndex / Summary 等插件调用）
    @abstractmethod
    def generate_aliases(self, concept) -> list[str]:
        """为概念生成别名（同义词、缩写、常见说法、易错写法）"""
        pass

    @abstractmethod
    def generate_summary(self, content: str, max_tokens: int = 100) -> str:
        """为内容生成紧凑摘要"""
        pass
```

### 3.4 NodeExtensionInterface - 节点数据扩展接口

```python
class NodeExtensionInterface(ABC):
    """节点数据扩展接口

    实现此接口的插件可在 node.extensions[plugin.name()] 下挂载自己的数据。
    """

    @abstractmethod
    def name(self) -> str:
        """插件名，对应 node.extensions 的 key"""
        pass

    @abstractmethod
    def schema(self) -> dict:
        """扩展字段类型定义，{field_name: type_str}

        用于文档化、验证、IDE 自动补全等。
        """
        pass

    @abstractmethod
    def default(self) -> Any:
        """新节点创建时该 slot 的默认值"""
        pass

    @abstractmethod
    def serialize(self, data: Any) -> dict:
        """转为可 JSON 化的字典（持久化用）"""
        pass

    @abstractmethod
    def deserialize(self, data: dict) -> Any:
        """从持久化字典恢复"""
        pass
```

### 3.5 PipelineHookInterface - 写入管线钩子

```python
class PipelineHookInterface(ABC):
    """写入管线钩子接口

    所有 on_<state> 方法默认空实现；插件只需重写关心的状态点。
    每个方法接收 HookContext，可读写 ctx 字段（含 ctx.skip = True 短路流程）。
    """

    def on_ingest_start(self, ctx: HookContext): pass
    def on_extracted(self, ctx: HookContext): pass
    def on_place_start(self, ctx: HookContext): pass
    def on_anchors_found(self, ctx: HookContext): pass
    def on_existence_checked(self, ctx: HookContext): pass
    def on_created_or_merged(self, ctx: HookContext): pass
    def on_fanout_checked(self, ctx: HookContext): pass
    def on_place_end(self, ctx: HookContext): pass
    def on_ingest_end(self, ctx: HookContext): pass
```

### 3.6 QueryHookInterface - 查询钩子

```python
class QueryHookInterface(ABC):
    """查询管线钩子接口（7 个状态点）"""

    def on_query_start(self, ctx: QueryContext): pass
    def on_seeds_located(self, ctx: QueryContext): pass
    def on_traverse_start(self, ctx: QueryContext): pass
    def on_traverse_step(self, ctx: QueryContext): pass
    def on_traverse_end(self, ctx: QueryContext): pass
    def on_synthesize_start(self, ctx: QueryContext): pass
    def on_query_end(self, ctx: QueryContext): pass
```

### 3.7 StorageSchemaExtensionInterface - 存储 schema 扩展（新）

```python
class StorageSchemaExtensionInterface(ABC):
    """存储 schema 扩展接口

    实现此接口的插件可向 StorageInterface 注册自己需要的列和辅助表。
    存储插件初始化时收集所有扩展定义，动态构建 schema。
    """

    @abstractmethod
    def name(self) -> str: pass

    @abstractmethod
    def node_columns(self) -> dict[str, str]:
        """{column_name: column_type_sql}，添加到 nodes 表

        例：{"sources_json": "TEXT"} 让 SourceTracking 在 nodes 表多一列。
        """
        pass

    @abstractmethod
    def auxiliary_tables(self) -> dict[str, str]:
        """{table_name: CREATE_TABLE_sql}，附加表

        例：{"document_chunks": "CREATE TABLE ..."} 注册一张完整辅助表。
        """
        pass
```

### 3.8 MaintenanceInterface - 维护接口

```python
class MaintenanceInterface(ABC):
    @abstractmethod
    def run(self, graph: GraphStore): pass

    @abstractmethod
    def should_run(self) -> bool: pass
```

---

## 4. 插件系统

### 4.1 Plugin 基类

```python
class Plugin(ABC):
    name: str                    # 插件名（也是 extensions key）
    version: str
    interfaces: list[type]       # 实现的接口列表

    def __init__(self, config: dict = None):
        self.config = config or {}

    @abstractmethod
    def initialize(self, context: PluginContext):
        """注册前由 PluginManager 调用"""
        pass

    @abstractmethod
    def shutdown(self): pass
```

### 4.2 PluginManager

```python
class PluginManager:
    def __init__(self):
        self.plugins: dict[str, Plugin] = {}
        self.interfaces: dict[type, list[Plugin]] = {}

    def register(self, plugin: Plugin):
        self.plugins[plugin.name] = plugin
        for iface in plugin.interfaces:
            self.interfaces.setdefault(iface, []).append(plugin)

    def get(self, interface: type) -> Plugin | None:
        plugins = self.interfaces.get(interface, [])
        return plugins[0] if plugins else None

    def get_all(self, interface: type) -> list[Plugin]:
        return self.interfaces.get(interface, [])

    def collect_schema_extensions(self) -> list[StorageSchemaExtensionInterface]:
        """供 StorageInterface 初始化时收集所有 schema 扩展定义"""
        return self.get_all(StorageSchemaExtensionInterface)

    def initialize_all(self, context: PluginContext):
        for plugin in self.plugins.values():
            plugin.initialize(context)

    def shutdown_all(self):
        for plugin in self.plugins.values():
            plugin.shutdown()
```

### 4.3 PluginContext

```python
@dataclass
class PluginContext:
    """插件运行上下文，注入到 Plugin.initialize()"""
    graph: GraphStore
    config: MCSConfig
    token_budget: TokenBudget
    serializer: Serializer
    plugin_manager: PluginManager   # 插件可通过此访问其他插件
```

---

## 5. 配置系统

### 5.1 配置定义

```python
@dataclass
class MCSConfig:
    mode: str = "knowledge_graph"      # "knowledge_graph" | "memory_system"
    token_budget: int = 8000
    plugins: list[str] = None
    plugin_configs: dict = None

    @classmethod
    def knowledge_graph(cls) -> "MCSConfig":
        return cls(
            mode="knowledge_graph",
            token_budget=8000,
            plugins=[
                "alias_index",       # Index + NodeExt(aliases) + PipelineHook
                "summary",           # NodeExt(summary) + PipelineHook
                "source_tracking",   # NodeExt(sources) + PipelineHook + SchemaExt
                "sqlite_storage",    # Storage
                "deepseek_llm",      # LLM
            ],
            plugin_configs={
                "sqlite_storage": {"path": "mcs.db"},
                "deepseek_llm": {"api_key": "", "model": "deepseek-chat"},
            }
        )

    @classmethod
    def memory_system(cls) -> "MCSConfig":
        return cls(
            mode="memory_system",
            token_budget=8000,
            plugins=[
                # Phase 1 plugins inherited
                "alias_index", "summary", "source_tracking",
                "sqlite_storage", "deepseek_llm",
                # Phase 2 plugins overlay
                "event_layer", "versioning", "confidence",
                "timeseries_entry", "gc", "arbitration",
            ]
        )
```

### 5.2 配置加载

```python
class ConfigLoader:
    @staticmethod
    def from_yaml(path: str) -> MCSConfig: pass

    @staticmethod
    def from_dict(data: dict) -> MCSConfig: pass
```

---

## 6. 第一期插件（5 个）

### 6.1 AliasIndexPlugin - 别名词典插件

实现三个接口：`IndexInterface` + `NodeExtensionInterface` + `PipelineHookInterface`

```python
class AliasIndexPlugin(Plugin, IndexInterface,
                        NodeExtensionInterface, PipelineHookInterface):
    name = "alias_index"
    interfaces = [IndexInterface, NodeExtensionInterface, PipelineHookInterface]

    def __init__(self, config=None):
        super().__init__(config)
        self.index: dict[str, list[str]] = {}    # term -> [node_ids]
        self.tokenizer = None
        self.llm = None

    def initialize(self, context: PluginContext):
        self.tokenizer = ChineseTokenizer()
        self.llm = context.plugin_manager.get(LLMInterface)
        self.build(context.graph)

    # === NodeExtensionInterface ===
    def schema(self): return {"aliases": "list[str]"}
    def default(self): return {"aliases": []}
    def serialize(self, data): return {"aliases": data["aliases"]}
    def deserialize(self, data): return data

    # === IndexInterface ===
    def build(self, graph):
        for node in graph.get_all_nodes():
            self.add_entry(node)

    def lookup(self, query: str) -> list[str]:
        terms = self.tokenizer.tokenize(query)
        node_ids = set()
        for term in terms:
            node_ids.update(self.index.get(term, []))
        return list(node_ids)

    def add_entry(self, node: Node):
        aliases = node.extensions.get(self.name, {}).get("aliases", [])
        for term in [node.name] + aliases:
            self.index.setdefault(term, []).append(node.id)

    def remove_entry(self, node_id: str):
        for term, ids in self.index.items():
            if node_id in ids:
                ids.remove(node_id)

    def update_entry(self, node: Node):
        self.remove_entry(node.id)
        self.add_entry(node)

    # === PipelineHookInterface ===
    def on_extracted(self, ctx: HookContext):
        """概念抽出后，为每个 concept 主动生成别名"""
        for c in ctx.concepts:
            if not getattr(c, "aliases", None):
                c.aliases = self.llm.generate_aliases(c)

    def on_created_or_merged(self, ctx: HookContext):
        """节点确定后，aliases 挂到 extensions 并更新索引"""
        node = ctx.node
        slot = node.extensions.setdefault(self.name, self.default())
        new_aliases = getattr(ctx.concept, "aliases", []) or []
        slot["aliases"] = list(set(slot["aliases"] + new_aliases))
        self.update_entry(node)
```

### 6.2 SummaryPlugin - 摘要生成插件

```python
class SummaryPlugin(Plugin, NodeExtensionInterface, PipelineHookInterface):
    name = "summary"
    interfaces = [NodeExtensionInterface, PipelineHookInterface]

    def initialize(self, context: PluginContext):
        self.llm = context.plugin_manager.get(LLMInterface)

    # === NodeExtensionInterface ===
    def schema(self): return {"text": "str", "generated_at": "datetime"}
    def default(self): return {"text": "", "generated_at": None}
    def serialize(self, data):
        return {"text": data["text"],
                "generated_at": data["generated_at"].isoformat() if data["generated_at"] else None}
    def deserialize(self, data):
        return {"text": data["text"],
                "generated_at": datetime.fromisoformat(data["generated_at"]) if data["generated_at"] else None}

    # === PipelineHookInterface ===
    def on_created_or_merged(self, ctx: HookContext):
        """节点创建或合并后，调用 LLM 生成摘要"""
        node = ctx.node
        slot = node.extensions.setdefault(self.name, self.default())
        if not slot["text"] or len(node.content) != slot.get("_content_len"):
            slot["text"] = self.llm.generate_summary(node.content)
            slot["generated_at"] = datetime.now()
            slot["_content_len"] = len(node.content)
```

### 6.3 SourceTrackingPlugin - 出处追踪插件

实现三个接口：`NodeExtensionInterface` + `PipelineHookInterface` + `StorageSchemaExtensionInterface`

```python
@dataclass
class Source:
    """概念出处（文档块级别）

    Phase 2 升级到事件层时，Source 可平滑扩展为引用 fact_id，schema 不破坏。
    """
    doc_id: str
    chunk_id: str
    content_hash: str
    section_title: Optional[str] = None


class SourceTrackingPlugin(Plugin, NodeExtensionInterface,
                            PipelineHookInterface,
                            StorageSchemaExtensionInterface):
    name = "source_tracking"
    interfaces = [NodeExtensionInterface, PipelineHookInterface,
                  StorageSchemaExtensionInterface]

    def initialize(self, context: PluginContext):
        self.storage = context.plugin_manager.get(StorageInterface)

    # === NodeExtensionInterface ===
    def schema(self): return {"sources": "list[Source]"}
    def default(self): return {"sources": []}
    def serialize(self, data):
        return {"sources": [asdict(s) for s in data["sources"]]}
    def deserialize(self, data):
        return {"sources": [Source(**s) for s in data["sources"]]}

    # === StorageSchemaExtensionInterface ===
    def node_columns(self):
        return {}                  # sources 走 extensions_json 列，不单独建列

    def auxiliary_tables(self):
        return {
            "document_chunks": """
                CREATE TABLE IF NOT EXISTS document_chunks (
                    doc_id TEXT,
                    chunk_id TEXT,
                    content_hash TEXT NOT NULL,
                    ingested_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    PRIMARY KEY (doc_id, chunk_id)
                )
            """
        }

    # === PipelineHookInterface ===
    def on_ingest_start(self, ctx: HookContext):
        """幂等检查：相同 (doc_id, chunk_id, content_hash) 第二次摄入则短路"""
        meta = ctx.metadata or {}
        doc_id, chunk_id = meta.get("doc_id"), meta.get("chunk_id")
        if not (doc_id and chunk_id): return

        content_hash = self._hash(ctx.text)
        if self._already_ingested(doc_id, chunk_id, content_hash):
            ctx.skip = True
            return

        # 暂存 Source，等节点确定后再挂上去
        ctx.metadata["_pending_source"] = Source(
            doc_id=doc_id, chunk_id=chunk_id,
            content_hash=content_hash,
            section_title=meta.get("section_title"),
        )

    def on_created_or_merged(self, ctx: HookContext):
        """节点确定后，把 Source 追加到 node.extensions"""
        source = (ctx.metadata or {}).get("_pending_source")
        if not source: return
        node = ctx.node
        slot = node.extensions.setdefault(self.name, self.default())
        slot["sources"].append(source)

    def on_ingest_end(self, ctx: HookContext):
        """登记 chunk 已摄入，下次同 chunk 再来则短路"""
        source = (ctx.metadata or {}).get("_pending_source")
        if source:
            self._record_chunk(source)

    # === 公共 API（暴露给应用层）===
    def update_document(self, doc_id: str, new_chunks: list,
                        pipeline: WritePipeline):
        """文档修订入口"""
        affected = self._find_nodes_by_doc(doc_id)
        old_keys = {(s.doc_id, s.chunk_id) for n in affected
                    for s in n.extensions.get(self.name, {}).get("sources", [])
                    if s.doc_id == doc_id}

        new_keys = set()
        for chunk in new_chunks:
            pipeline.ingest(chunk.text, doc_id=doc_id, chunk_id=chunk.id,
                            section_title=chunk.section_title)
            new_keys.add((doc_id, chunk.id))

        self._remove_source_refs(old_keys - new_keys)

    def purge_orphans(self, graph: GraphStore) -> list[str]:
        """清理 sources 为空的孤立节点；由调用方在批量修订完后显式触发"""
        orphans = [n for n in graph.get_all_nodes()
                   if not n.extensions.get(self.name, {}).get("sources")]
        for n in orphans:
            graph.delete_node(n.id)
        return [n.id for n in orphans]
```

### 6.4 SQLiteStoragePlugin - SQLite 持久化（支持 schema 扩展）

```python
class SQLiteStoragePlugin(Plugin, StorageInterface):
    name = "sqlite_storage"
    interfaces = [StorageInterface]

    def __init__(self, config=None):
        super().__init__(config)
        self.path = self.config.get("path", "mcs.db")
        self.conn = None

    def initialize(self, context: PluginContext):
        self.conn = sqlite3.connect(self.path)
        schema_extensions = context.plugin_manager.collect_schema_extensions()
        self._create_tables(schema_extensions)

    def _create_tables(self, schema_extensions: list):
        # 基础列（id / name / content / role / extensions_json）
        base_columns = [
            "id TEXT PRIMARY KEY",
            "name TEXT NOT NULL",
            "content TEXT",
            "role TEXT DEFAULT 'concept'",
            "extensions_json TEXT",  # 完整 extensions 字典的 JSON
        ]

        # 各插件注册的额外列
        ext_columns = []
        for ext in schema_extensions:
            for col_name, col_type in ext.node_columns().items():
                ext_columns.append(f"{col_name} {col_type}")

        nodes_sql = (f"CREATE TABLE IF NOT EXISTS nodes "
                     f"({', '.join(base_columns + ext_columns)})")

        # 各插件注册的辅助表
        aux_sql = ""
        for ext in schema_extensions:
            for _, create_sql in ext.auxiliary_tables().items():
                aux_sql += create_sql.strip() + ";\n"

        self.conn.executescript(f"""
            {nodes_sql};

            CREATE TABLE IF NOT EXISTS edges (
                source_id TEXT,
                target_id TEXT,
                direction TEXT DEFAULT 'bidirectional',
                PRIMARY KEY (source_id, target_id)
            );

            CREATE INDEX IF NOT EXISTS idx_edges_source ON edges(source_id);
            CREATE INDEX IF NOT EXISTS idx_edges_target ON edges(target_id);

            {aux_sql}
        """)

    def save_node(self, node: Node):
        self.conn.execute(
            "INSERT OR REPLACE INTO nodes "
            "(id, name, content, role, extensions_json) VALUES (?, ?, ?, ?, ?)",
            (node.id, node.name, node.content, node.role,
             json.dumps(node.extensions, default=str))
        )

    def save_edge(self, edge: Edge):
        self.conn.execute(
            "INSERT OR REPLACE INTO edges (source_id, target_id, direction) "
            "VALUES (?, ?, ?)",
            (edge.source_id, edge.target_id, edge.direction)
        )

    def save(self, graph: GraphStore):
        for node in graph.get_all_nodes():
            self.save_node(node)
        for edge in graph.get_all_edges():
            self.save_edge(edge)
        self.conn.commit()

    def load(self) -> GraphStore:
        graph = GraphStore()
        for row in self.conn.execute("SELECT * FROM nodes"):
            extensions = json.loads(row[4]) if row[4] else {}
            node = Node(id=row[0], name=row[1], content=row[2],
                        role=row[3], extensions=extensions)
            graph.add_node(node)
        for row in self.conn.execute("SELECT * FROM edges"):
            graph.add_edge(Edge(source_id=row[0], target_id=row[1],
                                 direction=row[2]))
        return graph
```

### 6.5 DeepSeekLLMPlugin - DeepSeek LLM 插件

```python
class DeepSeekLLMPlugin(Plugin, LLMInterface):
    name = "deepseek_llm"
    interfaces = [LLMInterface]

    def __init__(self, config=None):
        super().__init__(config)
        self.api_key = self.config.get("api_key")
        self.model = self.config.get("model", "deepseek-chat")
        self.base_url = self.config.get("base_url", "https://api.deepseek.com")

    def initialize(self, context: PluginContext):
        self.client = OpenAI(api_key=self.api_key, base_url=self.base_url)

    def call(self, prompt: str, system: str = None) -> str:
        messages = []
        if system: messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})
        resp = self.client.chat.completions.create(model=self.model, messages=messages)
        return resp.choices[0].message.content

    def extract_concepts(self, text): ...
    def check_exists(self, concept, subgraph): ...
    def decide_hub(self, subgraph): ...
    def decide_directions(self, query, current_node, subgraph, accumulated): ...
    def synthesize(self, query, content): ...

    def generate_aliases(self, concept) -> list[str]:
        """为概念生成别名（同义词、缩写、常见说法、易错写法）"""
        prompt = Prompts.GENERATE_ALIASES.format(
            name=concept.name, content=concept.content)
        return self._parse_aliases(self.call(prompt))

    def generate_summary(self, content: str, max_tokens: int = 100) -> str:
        prompt = Prompts.GENERATE_SUMMARY.format(
            content=content, max_tokens=max_tokens)
        return self.call(prompt)
```

---

## 7. 第二期插件（预留）

第二期插件通过配置叠加，不修改核心引擎；每个插件依然遵循 `NodeExtension + PipelineHook / QueryHook + SchemaExtension` 的组合模式：

| 插件 | 实现接口 | 职责 |
|---|---|---|
| EventLayerPlugin | StorageInterface + PipelineHookInterface + StorageSchemaExtensionInterface | 事实层独立存储 + 写入时记录 |
| VersioningPlugin | NodeExtensionInterface + PipelineHookInterface | extensions["versioning"] 版本链 |
| ConfidencePlugin | NodeExtensionInterface + PipelineHookInterface | extensions["confidence"] 置信度 |
| TimeSeriesEntryPlugin | QueryHookInterface | on_seeds_located 扩展时序入口种子 |
| GCPlugin | MaintenanceInterface | 周期性 GC 低置信 / 久未触发节点 |
| ArbitrationPlugin | QueryHookInterface | on_synthesize_start 对捞回版本做仲裁 |

---

## 8. 项目结构

```
mcs/
├── core/
│   ├── graph.py                  # Node (最小核心) | Edge | GraphStore
│   ├── token_budget.py
│   ├── serializer.py             # 含 get_summary helper
│   ├── write_pipeline.py         # WritePipeline | WritePipelineState | HookContext
│   ├── query_engine.py           # QueryEngine | QueryPipelineState | QueryContext
│   ├── plugin_manager.py
│   └── config.py
│
├── interfaces/
│   ├── storage.py
│   ├── index.py
│   ├── llm.py
│   ├── node_extension.py
│   ├── pipeline_hook.py          # 9 个 on_<state> 方法
│   ├── query_hook.py             # 7 个 on_<state> 方法
│   ├── storage_schema_ext.py     # 新增
│   └── maintenance.py
│
├── plugins/
│   ├── base.py                   # Plugin 基类
│   │
│   ├── phase1/                   # 第一期 5 个插件
│   │   ├── alias_index.py
│   │   ├── summary.py            # 新增
│   │   ├── source_tracking.py    # 新增（含 Source 数据类）
│   │   ├── sqlite_storage.py
│   │   └── deepseek_llm.py
│   │
│   └── phase2/                   # 第二期预留
│       ├── event_layer.py
│       ├── versioning.py
│       ├── confidence.py
│       ├── timeseries_entry.py
│       ├── gc.py
│       └── arbitration.py
│
├── prompts/
│   ├── extract.py
│   ├── place.py                  # check_exists
│   ├── merge.py                  # decide_hub
│   ├── traverse.py               # decide_directions
│   ├── synthesize.py
│   ├── aliases.py                # 新增（generate_aliases）
│   └── summary.py                # 新增（generate_summary）
│
├── utils/
│   ├── tokenizer.py
│   └── text_utils.py
│
└── examples/
    ├── basic_usage.py
    └── wiki_example.py
```

---

## 9. 使用示例

### 9.1 基本使用

```python
from mcs import MCS, MCSConfig

config = MCSConfig.knowledge_graph()
config.plugin_configs["deepseek_llm"]["api_key"] = "your-api-key"

mcs = MCS(config)

# 摄入文本（带出处元数据）
mcs.ingest(
    "深度学习是机器学习的一个子领域，它使用多层神经网络...",
    doc_id="dl-textbook-v3",
    chunk_id="ch1-sec1",
    section_title="第一章 1.1 引言"
)

# 查询
answer = mcs.query("什么是深度学习？")
print(answer)
```

### 9.2 文档修订

```python
# 修订某文档
source_tracking = mcs.get_plugin("source_tracking")
source_tracking.update_document(
    doc_id="dl-textbook-v3",
    new_chunks=[Chunk(id="ch1-sec1", text="...", section_title="第一章 1.1 引言（修订版）")],
    pipeline=mcs.write_pipeline,
)

# 批量修订后显式清理孤立节点
removed = source_tracking.purge_orphans(mcs.graph)
print(f"清理了 {len(removed)} 个孤立概念")
```

### 9.3 切换到 Phase 2 记忆系统模式

```python
config = MCSConfig.memory_system()
mcs = MCS(config)
# 核心代码完全不变，只是多了 6 个 Phase 2 插件
```

---

## 10. 扩展点总结

| 扩展点 | 接口 | 第一期实现 | 第二期扩展 |
|--------|------|-----------|-----------|
| 存储 | StorageInterface | SQLiteStorage | + EventLayer |
| 索引 | IndexInterface | AliasIndex | + TimeSeriesIndex |
| LLM | LLMInterface | DeepSeekLLM | 其他模型 |
| 节点数据扩展 | NodeExtensionInterface | aliases / summary / sources | + versions / confidence |
| 存储 schema 扩展 | StorageSchemaExtensionInterface | SourceTracking 注册 document_chunks 表 | + EventLayer 注册 facts 表 |
| 写入钩子 | PipelineHookInterface | AliasIndex / Summary / SourceTracking | + 矛盾检测、版本化、置信度更新 |
| 查询钩子 | QueryHookInterface | - | TimeSeriesEntry / Arbitration |
| 维护 | MaintenanceInterface | 手动 | 自动 GC |

---

## 11. 已知限制

- **同名异义查询消歧**：Phase 1 不实现查询端语义消歧。词法 `lookup` 命中多个同名节点时直接合并为种子集合，由 `_traverse` 的"判方向"步骤自然过滤。教科书场景下，同名异义通过节点 `name` 字段的去歧义化（如"苹果(科技公司)"）+ 共现概念间接缓解。Phase 2 起若需要再补 `LLMInterface.disambiguate(context, candidates)` 服务，写入端 `on_anchors_found` 和查询端 `on_seeds_located` 状态点已经预留接入位。

- **属性节点版本化**：Phase 1 通过 `SourceTrackingPlugin.update_document` 重新摄入处理文档修订，不保留版本历史。Phase 2 由 `VersioningPlugin` 通过 `extensions["versioning"]` 接入版本链。

- **存储增量写入**：Phase 1 SQLiteStoragePlugin 暂未订阅图变更事件，每次 ingest 后需调用方手动 `save()`。Phase 2 之前考虑给 PipelineHook 增加事件桥接（如把 CREATED_OR_MERGED 直接路由到 Storage.save_node）。

- **Token 估算精度**：Phase 1 使用简单字符级估算，与 LLM 真实 tokenizer 有差异。Phase 2 之前接 DeepSeek tokenizer endpoint 校准。

- **LLM 调用缓存**：当前无缓存层。一次查询走 5-10 步遍历 = 5-10 次 LLM 调用串行执行。生产环境前考虑在 LLMInterface 上加缓存装饰器。

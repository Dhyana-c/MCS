# Design: Unified Workflow Architecture

## 1. 定位声明

MCS 是**可扩展的记忆系统**（extensible memory system），不是问答系统。

| 维度 | 旧定位（问答） | 新定位（记忆） |
|------|----------------|----------------|
| 默认输出 | `str`（答案） | `List[Node]`（相关节点） |
| 合成动作 | 必走，`LLMInterface.synthesize` 强制实现 | 可选，由后置处理插件提供 |
| 多轮 | 不在范围 | 不在范围（由调用方处理；MCS 接受可选的 `existing_context` 入参） |
| 上层用法 | 直接对话 | RAG / Agent / Chatbot 把 MCS 当记忆层调用 |

这一定位决定了所有后续设计：插件链允许返回任意类型；语义遍历的"自然终点"是节点集合定型，而不是答案合成。

## 2. 读流程（Query / Recall）

```
INPUT: query_text, [existing_context]
   │
   ▼
┌─────────────────────────────────────────────────────────────┐
│ ① 前置插件链 (可选, 0..N, 串联)                              │
│   - 分词 / 时序信号注入 / 用户自定义                         │
│   - 接口: PostprocessPluginInterface (复用, 前置位置)        │
└─────────────────────────────────────────────────────────────┘
   │
   ▼
┌─────────────────────────────────────────────────────────────┐
│ ② 种子定位                                                   │
│   if existing_context: 跳到 ③ (多轮驻留)                     │
│                                                              │
│   入口插件链 (累积模式 + 优先级排序)                          │
│     ├─ AliasEntryPlugin       [priority 100]                │
│     ├─ TimeSeriesEntryPlugin  [priority 80, Phase 2]        │
│     ├─ UserCustomEntry        [priority 50..]               │
│     └─ HubFallbackEntryPlugin [priority 0]                  │
│                                                              │
│   合并 (按优先级排序、可声明 exclusive 短路后续)             │
│                                                              │
│   TrimPlugin: 裁到 ≤ T (统一接口, 同样可用于第 ④ 步)         │
│   ─→ seeds                                                  │
└─────────────────────────────────────────────────────────────┘
   │
   ▼
┌─────────────────────────────────────────────────────────────┐
│ ③ 语义理解 Loop (BFS, LLM + 代码协同)                       │
│                                                              │
│   visited     = set()        ← 防环 (图允许环)               │
│   accumulated = []                                           │
│   frontier    = seeds                                        │
│                                                              │
│   for round in 1..max_rounds:                                │
│     if not frontier: break                                   │
│     if len(picked) >= max_picked: break                      │
│                                                              │
│     next_frontier = []                                       │
│     for node in frontier:                                    │
│       if node.id in visited: continue                        │
│       visited.add(node.id)                                   │
│                                                              │
│       neighbors = graph.neighbors(node, hop=1, ≤T)           │
│       【LLM call】                                           │
│          purpose:   decide_directions                        │
│          nodes_in:  [node] + neighbors                       │
│          free_args: query, accumulated                       │
│          ─→ selected_ids (可为空)                            │
│                                                              │
│       accumulated  += [n for n in neighbors if n.id in ...] │
│       next_frontier += 选中                                  │
│                                                              │
│     frontier = next_frontier                                 │
│                                                              │
│   ─→ accumulated                                             │
└─────────────────────────────────────────────────────────────┘
   │
   ▼
┌─────────────────────────────────────────────────────────────┐
│ ④ 仲裁 (0 或 1 个插件，单一职责: List[Node] → List[Node])    │
│                                                              │
│   - PriorityArbitrationPlugin   按优先级硬截                 │
│   - LLMArbitrationPlugin        LLM 解冲突                   │
│   - <None>                      accumulated 全部透传         │
│                                                              │
│   ─→ selected (最终节点集，不再变)                           │
└─────────────────────────────────────────────────────────────┘
   │
   ▼
┌─────────────────────────────────────────────────────────────┐
│ ⑤ 后置处理链 (0..N, 串联, 输出形态自由)                      │
│                                                              │
│   - SynthesizePlugin     selected → str (合成答案)           │
│   - SubQueryPlugin       selected + query → 再来一轮         │
│   - SummarizePlugin      selected → 紧凑记忆条目             │
│   - 用户自定义                                               │
│                                                              │
│   ─→ result (任意类型)                                       │
└─────────────────────────────────────────────────────────────┘
   │
   ▼
OUTPUT: result   (默认 = selected, 即 List[Node])
```

## 3. 写流程（Ingest / Remember）

```
INPUT: text, metadata
   │
   ▼
┌─────────────────────────────────────────────────────────────┐
│ ① 前置插件链 (可选, 0..N, 串联)                              │
│   - 压缩 / 语义摘要 / 直接透传                               │
│   - 用户决定"记什么"——灵活: 原文/摘要/接入问答系统的会话总结│
│   ─→ processed_text                                          │
└─────────────────────────────────────────────────────────────┘
   │
   ▼
┌─────────────────────────────────────────────────────────────┐
│ ② 关联节点定位                                               │
│   ★ 复用读流程: query(processed_text) ─→ 关联节点集         │
│                                                              │
│   这一步让写入"先看图、再下笔"——避免命名漂移和重复创建      │
└─────────────────────────────────────────────────────────────┘
   │
   ▼
┌─────────────────────────────────────────────────────────────┐
│ ③ 概念提取 (LLM 一次，单一职责)                              │
│   【LLM call】                                               │
│     purpose:   extract_concepts                              │
│     nodes_in:  关联节点集 (让 LLM 参考已有命名)              │
│     free_args: processed_text                                │
│     ─→ List[ConceptDraft]                                   │
│        [{name, content, relation_hints}]                     │
└─────────────────────────────────────────────────────────────┘
   │
   ▼
┌─────────────────────────────────────────────────────────────┐
│ ④ 关系判定 (LLM 一次，单一职责)                              │
│   【LLM call】                                               │
│     purpose:   judge_relations                               │
│     nodes_in:  关联节点集                                    │
│     free_args: ConceptDrafts                                 │
│     ─→ DecisionList (纯数据, 不改图)                         │
│        [                                                     │
│          {action: "merge",  concept: c1, target: nodeA},    │
│          {action: "create", concept: c2,                    │
│            edges_to: [nodeB, nodeC]},                       │
│          {action: "attach_statement",                       │
│            target_attr_node: nodeD, statement: "..."},      │
│          ...                                                 │
│        ]                                                     │
└─────────────────────────────────────────────────────────────┘
   │
   ▼
┌─────────────────────────────────────────────────────────────┐
│ ⑤ 图更新 (无 LLM, 原子地应用决策清单)                        │
│   for decision in DecisionList:                              │
│     dispatch(decision) → GraphStore 原子操作                 │
│                                                              │
│   ─→ changed_nodes (新建/被合并/受影响的节点集)             │
└─────────────────────────────────────────────────────────────┘
   │
   ▼
┌─────────────────────────────────────────────────────────────┐
│ ⑥ 压缩判定插件链 (0..N, 条件触发, 串联)                      │
│   接收 changed_nodes, 各插件自行判断要不要触发               │
│                                                              │
│   - FanoutReducerPlugin     扇出超 T → 降扇出 (含 LLM 调用)  │
│   - CommunityMergerPlugin   社区密度阈值 → 合并              │
│   - SummaryRegenPlugin      内容变更 → 重生成 summary        │
│   - 用户自定义                                               │
│                                                              │
│   ★ 为 Phase 2 事件层 / GC / Versioning 预留扩展位          │
└─────────────────────────────────────────────────────────────┘
   │
   ▼
OUTPUT: 图状态更新完成
```

## 4. LLM 交互统一模式

所有 LLM 调用点（无论读写）都遵循同一种调用形态：

```
call(purpose, nodes_in: List[Node], free_args: dict) -> ParsedResult
   │
   ▼
┌──────────────────────────────────────────────────┐
│ 框架固定步骤                                       │
│  1. ContextRenderer.render(nodes_in, purpose)    │
│     ─→ rendered: str                             │
│  2. 装配 prompt:                                  │
│       system = system_for(purpose) [用户可覆盖]  │
│       user   = template_for(purpose).format(     │
│                  material=rendered,              │
│                  **free_args                     │
│               )            [用户可覆盖]          │
│  3. LLM 厂商适配 .call(system, user) → raw       │
│  4. parser_for(purpose)(raw) → parsed [可覆盖]   │
└──────────────────────────────────────────────────┘

purposes (固定 9 种):
  WRITE 侧:  extract_concepts, judge_relations,
             gen_aliases, gen_summary, decide_hub
  READ 侧:   decide_directions, navigate_hub
  共享:      arbitrate, synthesize

ContextRenderer 渲染规则:
  for node in nodes_in:
    yield render_core_fields(node)       # name, content/summary
    for ext_plugin in NodeExtensions:
      if ext_plugin.contributes_to(purpose):
        yield ext_plugin.render(node, purpose)
```

**关键变化点**：
- 旧 `LLMInterface.check_exists(concept, subgraph: str)` → 新调用 `call("check_exists" / "judge_relations", nodes_in=[...], free_args={...})`
- 旧 `Serializer.serialize(subgraph, mode="navigation"|"full")` → 新 `ContextRenderer.render(nodes_in, purpose)`，渲染内容由 purpose 决定，插件按 purpose 贡献片段
- 用户可在配置或代码层覆盖三件事：`system_prompt[purpose]`、`user_template[purpose]`、`parser[purpose]`

## 5. Context 对象

### 5.1 QueryContext（一次 query 的状态对象）

```
QueryContext {
  [1] system_prompt: str        ← 用户配置 (领域 + 角色), 整次调用不变
  [2] user_input:    str        ← 原始 query, 整次调用不变
  [3] intermediate:  List[Node] ← accumulated, ③ Loop 内在改
  [4] result_set:    List[Node] ← selected, ④ 之后定下来
  metadata: dict                ← 自由 slot
}
```

[3] 和 [4] 都是节点集合，但生命周期不同：[3] 是过程产物（可能更大、可能含冲突），[4] 是最终交付。

### 5.2 WriteContext（一次 ingest 的状态对象）

```
WriteContext {
  [1] system_prompt: str             ← 用户配置, 不变
  [2] user_input:    str             ← 原始 text, 不变
  [3] processed:     str             ← ① 前置处理后的 text
  [4] related:       List[Node]      ← ② 复用读流程得到的关联节点
  [5] concepts:      List[ConceptDraft] ← ③ 提取产物
  [6] decisions:     DecisionList    ← ④ 判定产物
  [7] changed:       List[Node]      ← ⑤ 应用后受影响的节点
  metadata: dict
}
```

## 6. 新插件接口清单

```
EntryPluginInterface
  - priority: int
  - exclusive: bool         (命中后是否短路后续低优先级)
  - locate(query, ctx) -> List[Node]

TrimPluginInterface
  - trim(nodes, budget) -> List[Node]
  - 可挂载点: ② 种子裁剪、④ 仲裁(作为 PriorityArbitration 的底层)

ArbitrationPluginInterface
  - arbitrate(accumulated, query, ctx) -> List[Node]
  - 每条管线 ≤ 1 个

PostprocessPluginInterface
  - process(input, ctx) -> Any   (输出形态自由)
  - 可挂载点: 读流程 ⑤、写流程 ①(作为前置)

CompactionPluginInterface
  - should_run(changed_nodes, graph) -> bool
  - run(changed_nodes, graph, llm_caller) -> None
  - 挂载点: 写流程 ⑥
```

以及保留/调整的旧接口：

```
保留不动:
  StorageInterface
  IndexInterface
  NodeExtensionInterface (但 render contribution 是新增能力)
  StorageSchemaExtensionInterface
  MaintenanceInterface

签名重写:
  LLMInterface  (新: purpose + nodes_in + free_args; 旧的 7 个语义方法删除)

删除:
  PipelineHookInterface  (9 状态点 hook 模型废弃)
  QueryHookInterface     (7 状态点 hook 模型废弃)
```

## 7. 与旧 architecture.md 的差异对照

| 旧 v2.0 | 新统一工作流 |
|---|---|
| `QueryEngine.query() -> str` | `QueryEngine.query() -> Any` (默认 `List[Node]`) |
| `WritePipeline` 9 状态点 hook | 写流程 6 段管线 + 5 类插件链 |
| `QueryEngine` 7 状态点 hook | 读流程 5 段管线 + 5 类插件链 |
| `LLMInterface.check_exists(concept, subgraph: str)` | `LLMInterface.call(purpose, nodes_in: List[Node], free_args)` |
| `Serializer.serialize(subgraph, mode)` | `ContextRenderer.render(nodes_in, purpose)`，插件按 purpose 贡献 |
| 词法召回 + 顶点兜底硬编码在 `_locate_seeds` | 入口策略全部插件化（含 `HubFallbackEntryPlugin`） |
| 写入抽概念不看图 | 写入复用读流程拿关联节点，让 LLM 抽概念时参考已有命名 |
| 存在性判定与图更新混在一步 | 决策（`DecisionList`，纯数据）与应用（改图）严格分离 |
| 合成答案是必走步骤 | 合成降级为可选后置插件 |
| 仲裁与后置混用 | 仲裁（≤1，选节点）与后置（多个，开放形态）分开 |

## 8. 16 项关键决策（对话过程沉淀）

| # | 决策 | 理由 |
|---|------|------|
| D01 | MCS 定位 = 可扩展记忆系统，非问答系统 | 多种上层（RAG/Agent/Chat）共用一个记忆层 |
| D02 | 默认 query 返回 `List[Node]`，合成是可选后置插件 | 与 D01 一致；不绑死输出形态 |
| D03 | 读流程 5 段（前置/定位/Loop/仲裁/后置） | 与写流程对称；段间职责单一 |
| D04 | 写流程 6 段（前置/定位/提取/判定/应用/压缩） | 决策/应用分离；压缩可插 |
| D05 | 写复用读做关联节点定位 | 避免命名漂移；统一"先看图再下笔" |
| D06 | 入口策略全部插件化（含兜底），累积+优先级 | 顶点导航是策略不是规则 |
| D07 | 裁剪和截取统一为 TrimPlugin 接口 | 同种动作（缩小节点集合），两个挂载位 |
| D08 | Loop = BFS + visited + max_rounds/max_picked 上限 | 图允许环；防死循环；硬上限作安全网 |
| D09 | 仲裁单一职责 ≤1，后置开放可串 | 仲裁是"选节点"，后置是"加工" |
| D10 | 写入概念提取 / 关系判定 分两次 LLM | 一次干一件事；prompt 紧凑；可独立调优 |
| D11 | 决策（数据）和应用（改图）严格分开 | 可观察 / 可重放 / 可干预 |
| D12 | 压缩判定插件化（为 Phase 2 事件层留扩展位） | 与写后置链对称；事件/版本/GC 都将走这里 |
| D13 | 写流程线性，分批 Loop 由调用方决定 | "宁可不合，不可错合"；漏合由社区合并兜底 |
| D14 | 写流程无独立仲裁位（决策步即仲裁） | 决策清单本身就是"对每个概念选定动作" |
| D15 | LLM 接口收 Node 对象，框架统一序列化 | 业务语义与厂商适配解耦 |
| D16 | system_prompt / user_template / parser 用户可覆盖 | Prompt 模板属于业务层，应可配置 |

每条决策都在对应的 spec delta 中以 Requirement 形式落地。

## 9. Phase 2 衔接点

新工作流为 Phase 2 插件预留了清晰的挂载位，不需要改动核心：

| Phase 2 插件 | 旧架构挂载位 | 新工作流挂载位 |
|---|---|---|
| EventLayerPlugin | `on_ingest_start` hook | 写流程 ① 前置插件链 + 写流程 ⑥ 压缩链（事件记录） |
| VersioningPlugin | `on_created_or_merged` hook | 写流程 ⑤ 图更新阶段的 `DecisionList` 扩展（新增 `attach_version` 动作） + `NodeExtensionInterface` 渲染贡献 |
| ConfidencePlugin | `on_created_or_merged` hook | 与 Versioning 同位 + 读流程 ④ 仲裁参考字段 |
| TimeSeriesEntryPlugin | `on_seeds_located` hook | 读流程 ② 入口插件链 |
| GCPlugin | `MaintenanceInterface` | 写流程 ⑥ 压缩插件链（条件触发） + 独立 `MaintenanceInterface` |
| ArbitrationPlugin | `on_synthesize_start` hook | 读流程 ④ 仲裁位（`LLMArbitrationPlugin`） |

## 10. 未决事项（不阻塞本 change 归档，留给 Phase 1 实现 change）

- **a. `processed_text` 作 query 的副作用**：写流程 ② 复用读流程会触发一次"内部 LLM 调用"（语义遍历 Loop），单次 ingest 的 LLM 调用数因此上升。是否在 Phase 1 提供"轻量定位模式"（只用入口插件不走遍历 Loop）作为优化路径？
- **b. `DecisionList` 的具体 schema**：本 change 定义 action 类型（merge/create/attach_statement/...），但每种 action 的字段细节留给 Phase 1 落地时具体设计。
- **c. ContextRenderer 的字段贡献协议**：`NodeExtensionInterface.render(node, purpose)` 的返回类型（str? structured? section name?）需要在 Phase 1 实现时定型。
- **d. system_prompt 覆盖的粒度**：是按 `purpose` 全局覆盖，还是允许 per-call 覆盖？倾向前者，但留给 Phase 1 决定。
- **e. 写流程 ② 复用读流程时使用的 query 形态**：直接用 `processed_text` 整段，还是再抽关键词？Phase 1 默认整段，前置插件可改。

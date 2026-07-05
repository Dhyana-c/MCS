## Context

统一图模型（`unified-graph-schema`）下：
- **边方向**：事件/事实 → 概念（命题指向端点、事件背书核心），概念作 target。
- **载重规则**：核心节点（概念/事实）`get_relations` 过滤事件边，防最热节点把全部事件漏回 LLM 上下文撑爆窗口。
- **孤儿挂 root**：零关联（`get_relations` 空）才挂 `__seed_root__`。

`graph_view`（人面可视化）原样继承载重 + 下钻只看 source 出边，导致：概念无出边（下钻空）、事件作出边但前端禁下钻、只被事件背书的概念 `get_relations` 空 → 误判孤儿挂 root。从 root 走 1 跳到底，9/14 节点不可达。`degree` 公式 `下钻子数 + 关系边度数` 在统一模型下对同一批邻居翻倍。

## Goals / Non-Goals

**Goals:**
- 图谱从 root 出发能导航到全部节点（事件/事实/概念）。
- `degree` 反映真实连接度（不翻倍）。
- 载重契约与 LLM 查询路径零影响。

**Non-Goals:**
- 不改 `get_relations` 签名/载重行为（载重仍约束 LLM 路径）。
- 不动 query_engine / 写管线 / 聚类。
- 不让 `source` 可下钻（db 无、意义不大）。
- 不解决「按摩带时间/今天未解析」等抽取质量问题（另立 change）。

## Decisions

### D1. 载重只约束 LLM 路径，graph_view 复用 `get_related_events` 绕载重

**选择**：`_do_graph_view` 用 `store.get_related_events`（store 既有方法，注释明写「定向查事件（绕载重规则）」）补事件节点，`get_edges_between` 取事件→焦点边。`get_relations` 一字不改。

**why**：载重的本意是防 LLM 上下文撑爆（铁律一）。graph_view 是人面视图、不进 LLM 上下文、不影响 priority 截断 —— 没理由继承载重。`get_related_events` 本就是 store 为「核心需要看事件」设计的绕载重方法（recall 用它），复用它语义清晰、零新接口。

**alternatives**：
- 给 `get_relations` 加 `include_events` 参数破载重 —— 污染载重契约、影响所有调用者。否决。
- 给 graph_view 新写全量边查询 —— 重复 `get_related_events` 逻辑。否决。

### D2. 事件可下钻（前端去 class 预判）

**选择**：`graph.html` 删 `DRILLABLE` 集合，所有节点右键都可 `expand`；事件 expand 返回其 `事件→概念/事实` 出边（get_out_hierarchy），`source`/孤立返回空标叶子。

**why**：事件作出边丰富（事件→概念/事实），是全图可达的关键一跳。事件可下钻纯只读（不改图、不聚类、不进 LLM）。去掉 class 预判后，「是否叶子」由 expand 返回空判定（语义更准），而非 class 假设。

**tradeoff**：违反旧「事件是叶子」前端契约（spec 同步）。失去「据 class 预判不发请求」的优化（事件现在也发请求，空则标叶子）—— 可视化正确性优先于省一次请求。

### D3. `edges` 按 `edge.id` 去重

**选择**：`edges = rel_edges + event_edges`，按 `edge.id` 去重。

**why**：真实 store 载重过滤使 rel_edges / event_edges 不重叠，但 FakeStore（测试）不做载重会重叠。去重让 `_do_graph_view` 不依赖 store 的载重实现细节，对任何 store 都正确。

### D4. `degree` 改「不同邻居数」

**选择**：`_degree` = rel_edges 端点 ∪ 相关事件 的 id 去重数。

**why**：旧 `下钻子数 + 关系边度数` 是旧模型（hierarchy / relations 两套不重叠）公式。统一模型层级=关联，下钻成员即关系端点，相加翻倍。改邻居去重还原真实热度（含事件背书）。

## Risks / Trade-offs

- **[事件下钻违反叶子契约]** → spec 同步（`graph-visualization` requirement 4 改）；前端 hint 更新；测试 `test_event_endorsement_visible_in_view` 钉死事件可见。
- **[载重豁免被误读为破坏铁律]** → design D1 明确：`get_relations` 不改、载重仍约束 LLM 路径；graph_view 走独立 `get_related_events`。代码注释 + spec 双重说明。
- **[root 视图事件过多撑挤]** → 长期靠归纳（hub）收敛；当前数据量小，非问题。本 change 不解决。

## Why

图谱页面只显示 4-5 个点（root + 4 个孤儿概念），但 db 里 14 节点。根因是边方向（事件/事实 → 概念，概念作 target）与下钻方向（只看 source 出边）不匹配，叠加载重过滤让孤儿判定失真，导致 9 节点从 root 不可达。同时 `degree` 在统一模型下翻倍（旧公式 `下钻子数 + 关系边度数` 对同一批邻居重复计数）。可视化本该让人看到全貌，却受 LLM 载重规则连累。

## What Changes

- **graph_view 补事件邻域**：`_do_graph_view` 用 `store.get_related_events`（store 已有的「绕载重」方法）补背书焦点的事件节点，用 `get_edges_between` 取事件→焦点边；`edges` 按 `edge.id` 去重兜底 store 实现差异。**`get_relations` 一字未改** —— 载重契约不动。
- **degree 改邻居去重**：`_degree` 从「下钻子数 + 关系边度数」改为「不同邻居数（rel 端点 ∪ 相关事件，去重）」，修复统一模型下的翻倍。
- **事件可下钻** **BREAKING**（前端契约）：`graph.html` 删 `DRILLABLE` class 预判，事件节点可右键下钻（展开其 `事件→概念/事实` 出边）。违反旧「事件是叶子」契约。`source` 仍叶子（db 无、expand 空标叶子）。
- **载重适用边界细化**：明确载重只约束 LLM 查询路径（防上下文撑爆），不约束 graph_view 可视化。

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

- `graph-visualization`: ① `graph_view` 的 nodes/edges 含事件背书（用 `get_related_events` 绕载重）；② `degree` 改不同邻居数；③ 事件可下钻（去叶子预判）；④ edges 按 id 去重。

## Impact

- **`mcs_agent/memory.py`**：`_do_graph_view` 补事件邻域 + edges 去重；`_degree` 邻居去重。
- **`mcs_mem/static/graph.html`**：删 `DRILLABLE` 限制、hint 文案。
- **`tests/test_graph_view.py`**：FakeStore 加 `get_related_events` / `get_edges_between`；degree 断言；新增 `test_event_endorsement_visible_in_view`。
- **`openspec/specs/graph-visualization/spec.md`**：degree、事件邻域、事件可下钻的 requirement / scenario 同步。
- **载重 / LLM 路径零影响**：`get_relations` 不改、query_engine 不改；可视化走 `get_related_events`（store 既有的绕载重方法）。

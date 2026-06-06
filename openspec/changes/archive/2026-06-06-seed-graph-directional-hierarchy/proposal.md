## Why

已落地的"持久虚拟根 + 递归分层种子图"（`__seed_root__` + `fanout_reducer` 维护 + 查询只读 + `hub_fallback` 从根 BFS 下钻）在 200 篇整篇实跑中暴露两个结构性问题：

1. **层级边无方向、无类型**：归纳重组产出的是**双向星型**边，且删除了 `node↔member`，使"层级边"与"语义边"无法区分；双向 + 兜底导航在缠绕结构里来回打转（成环）。
2. **hub 归纳退化（catch-all）**：根挂全主题概念、社区主题高度分散时，`decide_hub` 反复造出"涵盖医药/体育/娱乐/科技/政治…的综合信息聚合枢纽"这类**万能 hub**（实测日志可见 `f22410d1`、`2449e69e`、`0514587b` 等多个），层级既不收敛也无意义。

这两点让分层种子图的"可导航、可区分、可收敛"目标无法达成；趁结构刚成形先把方向语义与抗退化策略定下来。

## What Changes

- **层级边改为有向 + 保留上行边**（**BREAKING**：改变 `_reorganize` 的边拓扑与方向）。对 `a<->b, a<->c` 基于 `{b,c}` 提出中间 hub `d`，目标拓扑为：
  - 下行（父→子）：`a→d`、`d→b`、`d→c`
  - 上行（成员回指原父）：`b→a`、`c→a`
  - 即不再删除 `a-b/a-c`，而是改为**有向** `b→a/c→a`；新增**有向** `a→d/d→b/d→c`。
- **方向感知的图原语**：`GraphStore` 支持按方向取邻居（区分 out/in），`add_edge` 的 `direction="out"` 真正贯通到邻接与持久化。
- **方向感知的导航**：`navigate_hub` / `hub_fallback._navigate` 仅沿 **out 边**自顶向下下钻，以区分"层级"与"语义"、避免双向缠绕成环。
- **语义边保持双向**：`judge_relations` 的 `edges_to` / `edges_to_names` 仍为 `bidirectional`（检索可达性）。
- **抗退化的 bounding 策略**：避免 catch-all 万能 hub。候选机制：限制单次 `decide_hub` 的社区规模/分批；按主题或来源预分组再聚类；对过于宽泛的合成 hub 做拒绝/重试；合成 hub 去重（近义 hub 合并）。

## Capabilities

### New Capabilities
- `seed-graph-hierarchy`: 持久化的**有向分层**种子图——层级边有向（父→子 + 成员上行回指）、与语义边可区分；配套方向感知的图原语与自顶向下导航；以及抗退化（避免 catch-all）的递归 bounding 策略。

### Modified Capabilities
<!-- 现有 seed_graph_bounding 行为此前未单独成 capability spec（散落在 fanout/hub 实现）；本次以新 capability 收口，不在此声明 Modified。 -->

## Impact

- 代码：`mcs/plugins/phase1/fanout_reducer.py`（`_reorganize` / `_maintain_seed_root` / `_resolve_hub`）、`mcs/core/graph.py`（`add_edge` / 方向感知 `get_neighbors`）、`mcs/plugins/phase1/hub_fallback.py`（`_navigate`）、`mcs/core/query_engine.py`。
- 持久化：有向边经 `save_node`/`save_edge`/`save_full` 与 `load` 已支持 `direction`；需确认方向在 round-trip 中保真。
- 行为：层级边拓扑/方向变化属 **BREAKING**——既有用旧（双向星型）逻辑建出的图（如 `multihop_chat_200_v2`）与新逻辑不一致，需重建才能对齐新语义。
- 不影响：`judge_relations` 语义边（仍双向）、写入管线其余阶段、默认后端选择。

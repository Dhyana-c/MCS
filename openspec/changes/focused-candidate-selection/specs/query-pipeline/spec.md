## ADDED Requirements

### Requirement: 聚焦候选集选择（充分性裁剪）

查询阶段③ 遍历结束后，框架 SHALL 在把 `accumulated` 交给后处理（doc_rerank / 裁剪）之前，进行**聚焦候选集选择**：由 LLM 从 `accumulated` 中选出"足以回答查询的最小聚焦子集"，**仅该子集进入后处理排序**，以治理宽召回 BFS 收入旁支噪声、稀释排序、把 gold 压低名次的问题。

该选择 MUST 满足：
- **只减不增**：聚焦子集 MUST 是 `accumulated` 的子集，MUST NOT 引入新节点。
- **不牺牲召回的兜底**：当聚焦子集为空、或规模显著低于下限阈值时，框架 MUST 回退使用未裁剪的 `accumulated` 全集，确保聚焦不会导致召回（reached）下降。
- **探索期不早停**：聚焦判断 MUST 发生在遍历结束之后，MUST NOT 改变遍历期的终止条件（不得据此提前停止 BFS）——以隔离弱模型（如 deepseek）"自判充分即早停"的失召回风险。
- **可观测对照**：聚焦选择 SHALL 可开关，便于 on/off 同口径对照其对 reached / hit@k 的影响。

> 注：本要求延续 `separate-accumulate-frontier` 的"探索口径 ≠ 输出口径"解耦，治理的是 `accumulated → 最终候选集` 这一段的聚焦度；不改变不变量 `accumulated ≤ T`。

#### Scenario: 聚焦子集只减不增

- **WHEN** 对 `accumulated` 执行聚焦候选集选择
- **THEN** 输出 MUST 是 `accumulated` 的子集；MUST NOT 含 `accumulated` 之外的节点

#### Scenario: 空/超剪回退兜底

- **WHEN** 聚焦选择返回空、或子集规模低于下限阈值
- **THEN** 框架 MUST 回退使用 `accumulated` 全集进入后处理，MUST NOT 因聚焦导致最终候选集召回下降

#### Scenario: 聚焦发生在遍历之后、不影响终止

- **WHEN** 启用聚焦候选集选择
- **THEN** 阶段③ 遍历的终止条件 MUST 不变（不得据聚焦/充分性判断提前停止 BFS）；聚焦 MUST 仅作用于遍历产物 `accumulated`

#### Scenario: 可开关对照

- **WHEN** 聚焦选择被关闭
- **THEN** 框架行为 MUST 等价于未引入本要求前（`accumulated` 全集直接进后处理），便于同口径对照

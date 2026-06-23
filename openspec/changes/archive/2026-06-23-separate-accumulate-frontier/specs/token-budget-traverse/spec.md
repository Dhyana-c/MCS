## MODIFIED Requirements

### Requirement: 遍历流程实现用户定义的语义

The system SHALL implement `_traverse` with batch expansion. Selected items carry a **dual role** (`结果` / `探索` / both) from the `select_facts` call; routing is by role. The flow is:

1. Initialize: `accumulated = []`, `visited = set()`, `frontier = [...seeds]`, `used_tokens = 0`, `estimate_cache = {}`
2. Pack batch: greedily take nodes from `frontier` until `batch_tokens >= T * 0.8`. Shared neighbors across centers MUST be counted only once in batch_tokens estimation.
3. Load neighbors for each center in the batch. Use `{id: node}` dict for O(1) lookup.
4. LLM filter: `result_idx, frontier_idx = select_facts(nodes_in=[*centers, *all_neighbors], query, accumulated)` — output carries dual role
5. Route by role:
   - For each `结果` item (incl. both): if not visited, add to `accumulated` and `visited`, increment `used_tokens += estimate_node(node, estimate_cache)`. Selected fact-edge endpoints inherit the edge role.
   - For each `探索` item (incl. both): if not visited, add to next `frontier` and `visited`. MUST NOT add to `accumulated`. MUST NOT increment `used_tokens`.
6. If `used_tokens > budget` → terminate
7. Repeat steps 2-6 until `frontier` empty or any safety valve trips

#### Scenario: 完整遍历流程

- **WHEN** 调用 `_traverse(seeds, query, ctx)`
- **THEN** 框架 MUST 按上述批量扩展 + 角色路由流程执行

#### Scenario: 结果角色入 accumulated 并计 token

- **WHEN** 某条目被标 `结果` 且未 visited
- **THEN** 框架 MUST 加入 `accumulated` 与 `visited`，并 `used_tokens += estimate_node`

#### Scenario: 探索角色入 frontier 不计 token

- **WHEN** 某条目被标 `探索`（未标 `结果`）且未 visited
- **THEN** 框架 MUST 加入下一轮 `frontier` 与 `visited`，MUST NOT 加入 `accumulated`，MUST NOT 改变 `used_tokens`

#### Scenario: 每轮后检查预算

- **WHEN** 一轮批量扩展完成，新 `结果` 节点加入 `accumulated`
- **THEN** 框架 MUST 检查增量维护的 `used_tokens`；若 > `token_budget.T`，终止遍历

#### Scenario: 事实边端点随角色

- **WHEN** 选中一条事实边，其端点未被直接选中
- **THEN** 端点 MUST 按该边角色补入（`结果` → `accumulated`；`探索` → `frontier`）

#### Scenario: 种子不进初始 visited

- **WHEN** `_traverse` 初始化（seeds 入 `frontier`）
- **THEN** seeds MUST NOT 进入初始 `visited`（`visited = set()`）；首轮 LLM 把种子标 `结果` 时 `_consume` MUST 能将其加入 `accumulated`（否则 `if sel_node.id not in visited` 命中跳过 → 种子永失 accumulated，确定性 bug）

#### Scenario: 未裁决的孤立/叶子中心仍被评估

- **WHEN** frontier 中心节点无下钻成员且无关系边，且**不在 `visited`**（未裁决，如种子）
- **THEN** `_node_view` MUST 返回 `([node], [])`（单节点视图），使该节点进 LLM 评估、有机会被标 `结果`；MUST NOT 因无视图而在 LLM 调用前 skip

#### Scenario: 已裁决的无视图叶子跳过

- **WHEN** frontier 中心节点无下钻成员且无关系边，且**已在 `visited`**（已裁决，如上轮被标 `探索` 的跳板）
- **THEN** `_node_view` MUST 返回 `(None, None)` 跳过，避免对已裁决叶子空转 re-eval（`_consume` 必因 visited 跳过、无新增）

## ADDED Requirements

### Requirement: frontier 规模安全阀

The system SHALL enforce `max_frontier_nodes` as a safety valve. After decoupling, `探索` items no longer consume `T`, so `used_tokens` no longer bounds `frontier` growth and `max_rounds` only bounds depth — `frontier` width MUST have its own valve to prevent unbounded LLM-call fan-out. `QueryEngine.__init__` SHALL accept `max_frontier_nodes: int` (conservative default 500).

#### Scenario: __init__ 新增 max_frontier_nodes 参数

- **WHEN** 检查 `QueryEngine.__init__` 签名
- **THEN** 参数列表 MUST 包含 `max_frontier_nodes: int`（默认 500）

#### Scenario: frontier 超阀停止入队

- **WHEN** 构建下一轮 `frontier`（`next_frontier`）时其规模达到 `max_frontier_nodes`
- **THEN** 框架 MUST 停止继续向 `next_frontier` 入队；当前轮已选 `结果` MUST 照常进 `accumulated`（非整体终止；区别于 `max_accumulated_nodes` 撞阀的整体终止）

#### Scenario: 正常情况安全阀不触发

- **WHEN** 图扇出正常、`结果`/`探索` 标注合理
- **THEN** 遍历 MUST 由 token 预算或 LLM 自然收敛终止，而非 frontier 安全阀

## Why

当前 `_traverse` 阶段 ③ 采用「逐节点扩展」策略：每次从 queue 取一个节点，加载其全部邻居，一次性送 LLM 筛选。这导致频繁的小规模 LLM 调用（每个节点一次），增加延迟和成本。

优化方案：在 token 预算允许的前提下，将多个节点及其邻居**合并**后一次性送 LLM 筛选。只要合并后的总 token ≤ T，单次调用可覆盖多个节点的扩展，减少 LLM 调用次数，提升遍历效率。

## What Changes

- **_traverse 批量扩展**：队列中的节点不再逐个处理，而是按 token 预算打包成批次，每批次包含多个节点及其邻居，一次性送 LLM 筛选
- **select_nodes 提示词适配**：模板需支持多中心节点的场景，明确区分"中心节点"与"邻居候选"
- **批量筛选结果解析**：LLM 返回的节点 ID 需正确归类到各自所属的中心节点，以正确计算扩展深度

## Capabilities

### New Capabilities
- `batch-neighbor-traverse`: 批量邻居扩展遍历 — 将多个节点及其邻居合并后一次 LLM 调用，只要 token 总量不超预算

### Modified Capabilities
- `query-pipeline`: 阶段 ③ 的遍历策略从「逐节点扩展」变为「批量扩展」，需更新规范中的相关 requirement
- `token-budget-traverse`: 批量扩展场景下的预算控制、分批逻辑、深度计算规则需细化

## Impact

- **代码修改**：
  - `mcs/core/query_engine.py` — `_traverse` 方法重构
  - `mcs/prompts/select_nodes.py` — 提示词模板调整（支持多中心节点）
- **规范更新**：
  - `openspec/specs/query-pipeline/spec.md`
  - `openspec/specs/token-budget-traverse/spec.md`
- **兼容性**：LLM 调用签名不变（`nodes_in` 列表、`free_args` 结构），只是 `nodes_in` 中可能包含多个中心节点及其各自的邻居
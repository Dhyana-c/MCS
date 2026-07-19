## Why

LoCoMo conv-26 试点实测暴露 `associate` 工具的架构错配：其实现是 `mcs.query("", existing_context=[种子])`——**agent 每调一次 associate 就触发一整条框架 BFS 查询管线**（内含逐层 `select_facts` LLM 筛选）。实测 194 题 ×3 版重跑：管线内 `select_facts` 被调 **14691 次、输入 21.2M token**（每题 ~30 次，是 agent 顶层调用的 6 倍），单题延迟 60-80s、上下文峰值 30-60K 的主要来源。

根因是**双重游走**：agent 的多轮探索本身就是语义游走（相关性判断是 agent 的本职），工具内再嵌一层"BFS + LLM 筛选"是重复建设——框架 BFS 是为"一次性查询"设计的重管线，不是 agent 的探索原语。[[framework-to-agent-handoff]] 的自然深化。

超级 hub 放大了代价：peer-to-peer 对话语料中说话人是几乎所有命题的端点（conv-26 实测 Sarah deg=138 / Jessica deg=111），以主角为种子的 BFS 邻域巨大。

## What Changes

- `MemoryStore.associate` 新增 **`neighbors` 模式并设为默认**：一跳邻居纯图读（`store.get_relations`，载重双类过滤天然继承）、**零 LLM 调用**；互斥邻居单列在前（信号强）；邻居数截断（默认 60，`limit` 参数可调），超出提示剩余数与下钻方式
- 旧 BFS 重管线保留为显式 **`mode="mcs"`**（明确要框架级语义游走时用），渲染仍走 `render_query_result`
- `tools.py` associate handler 默认 mode 改 `neighbors`、新增 `limit` 参数、schema description 更新（标注两模式成本差异）
- spec delta：memory-agent「渲染复用」requirement 精确化（`render_query_result` 仅约束 `mcs` 模式）+ associate 语义 requirement

## Capabilities

### Modified Capabilities
- `memory-agent`: associate 默认语义从"全管线 BFS"改为"一跳邻居纯图读"；渲染复用约束按模式精确化

## Impact

- 受益：所有 agent 场景（bench / mcs_mem / mcs_mcp）——associate 成本从"每次一条查询管线（~15 次 LLM）"降到 **0 次 LLM**；预期 LoCoMo 单题延迟 60-80s → ~15s、管线成本降一个数量级、上下文瘦身
- 行为变化：agent 收到的 associate 结果从"BFS 筛选后的子图渲染"变为"一跳邻居列表（互斥前置、截断标注）"——探索深度由 agent 多轮驱动（每步可控、可解释）
- `mode="mcs"` 完全保留旧行为，需要框架级游走的调用方显式传参

## Why

记忆 agent 的 5 个导航工具要么是**纯读导航**（search / associate / reason / recall），要么是**整段写入**（learn）。缺一类「对已捞到的若干节点做**语义判断**」的只读工具：

- **归纳**——agent 用 search / associate 捞到几个概念后，没有手段直接问「这几个概念的共性 / 公共上位概念是什么」，只能靠自身猜测，容易脱钩于图里真实存的节点。
- **仲裁**——图里存着 `互斥` 的事实（事实 ↔ 事实，`judge_relations` 写入时标记），但**从不裁决谁对**；agent 撞见矛盾说法时没有工具据「背书事件」判定采信哪个。

两者都是「**图谱 + LLM 协作的只读语义判断**」——读图取节点（仲裁还反查背书事件）、喂 LLM、返回结论。补齐后 agent 能对已浮出的关系与矛盾做有据推理，而非止步于导航。

## What Changes

- **新增 `generalize` 工具（归纳·只读）**：给定若干节点 id → 经新 purpose `generalize` 让 LLM 概括它们的公共上位概念 → 返回含结论的文本（帮 agent 理解这些节点的关系 / 共性）。**不建节点、不改图**；概念不做事件反查；输入素材按 token 上界 T 有界（防爆 LLM 上下文）。
- **新增 `arbitrate` 工具（仲裁·只读）**：给定若干互斥事实 id + 问题 / 语境 → **图谱反查**每个事实的背书事件（`store.get_related_events(fact_id, limit=K)`，时间倒排、绕载重规则的定向查）→ 组装「互斥事实 + 关联事件」素材 → 经新 purpose `adjudicate` 让 LLM 裁决**采信哪个事实 + 理由** → 返回文本。**不改图**。
- **仲裁的「守门」= 读侧素材有界**：素材总 token 受 **T** 上界约束；事件过多时按「每事实最近 K 条 → 仍超 T 则**轮转保底**丢事件（每事实至少留 1 条、优先丢剩余事件最多的事实里最旧一条，再到 0）」截断，直到 material ≤ T（估算口径 == 渲染口径，对完整 material 整体估算、复用 recall 纪律）。**非写入期守门 / 裂变**——仲裁只读、不触发写。
- **2 个新提示词**：`mcs/prompts/generalize.py`、`mcs/prompts/adjudicate.py`，注册进 `DEFAULT_PROMPTS`。不复用 `synthesize`（按 query 合成答案、语义不符）、不复用 `decide_hub`（社区划分结构过重）；仲裁不复用现有 `arbitrate` purpose（只返回 id、无理由、也不吃事件），故新增 `adjudicate`、不动共享的 `arbitrate`。
- **LLM 来源 = MCS 的 LLM 插件**（非 agent chat LLM）：MemoryStore 经 `mcs.read_manager.get_all(PluginType.LLM)` 取（单实例）LLM 插件、调 `plugin.call(purpose, nodes_in, free_args)`——与 `learn` / `associate` 在 worker 线程触发 LLM 同一既定模式；handler 仍是 `(memory, args) -> str` 纯薄封装，trace / 异常隔离仍留在 `_dispatch`。
- **默认工具集 5 → 7**（增量、非破坏）：`ToolsetConfig` 默认 `enabled=None` 现含 `generalize` / `arbitrate`；`DEFAULT_SYSTEM_PROMPT` 补两工具说明。
- **不动框架层**：`mcs/core` 逻辑一行不改、不动写 / 查管线、不动存储、不改图——两工具纯只读消费 `store.get_node` / `get_related_events` + `query_engine.token_budget`。

## Capabilities

### New Capabilities

（无）

### Modified Capabilities

- `memory-agent`：
  - `记忆工具集` requirement 由「默认 5 个」改为「默认 7 个（learn / search / associate / reason / recall / **generalize** / **arbitrate**）」，补两条分发映射。
  - 新增 `generalize 原语（归纳概括）` requirement：给定节点 id → LLM 概括公共上位概念 → 文本；只读、T 有界、不改图。
  - 新增 `arbitrate 原语（互斥裁决）` requirement：给定互斥事实 id + 问题 → 反查背书事件 → 素材 T 有界截断 → LLM 裁决采信方 + 理由 → 文本；只读、不改图。

## Impact

- **代码**：
  - `mcs/prompts/generalize.py`、`mcs/prompts/adjudicate.py`（新 purpose 的 system / template / parse）+ `mcs/prompts/__init__.py` 注册进 `DEFAULT_PROMPTS`。
  - `mcs_agent/memory.py`：新增 `generalize(node_ids, focus?)` / `arbitrate(node_ids, question)` 两原语（worker 线程内取节点 / 反查事件 / T 截断素材 / 调 LLM 插件 / 渲染返回）+ 复用行级事件渲染口径（`_render_event_line`，arbitrate 自建素材装配、不套含 recall header 的 `_render_events`）；material 经 `free_args["material"]` 显式传 LLM（估算==投喂同源）。
  - `mcs_agent/tools.py`：`BUILTIN_TOOLS` 加 `generalize` / `arbitrate` 两 `ToolSpec` + handler；`MEMORY_TOOLS` 废弃别名随之含 7。
  - `mcs_agent/loop.py`：`DEFAULT_SYSTEM_PROMPT` 补两工具说明。
- **测试**：`tests/test_agent_memory.py` 新增 `generalize` / `arbitrate` 正向 + 边界用例（节点不存在、事件为空、事件过多→T 截断、LLM 解析失败隔离为 `[error]`、worker 线程只读、分发）；`tests/test_agent_tools.py` / `test_agent_loop.py` / `test_agent_trace.py` 的 mock 工具集补齐两新工具的调度 mock。
- **文档**：`docs/memory-agent.md` 工具表加两行、5→7、补「仲裁反查事件 + T 守门」说明。
- **API / 依赖**：无新增依赖；工具名 `generalize` / `arbitrate` 为增量新增，公共 API 签名均 `(*, node_ids, ...) -> str`，无 BREAKING。
- **不变量**：两工具只读、经单 worker 线程、不触发写 / 守门 / 裂变；仲裁虽反查事件但用定向 `get_related_events`（绕载重规则的独立检索步、不进常驻活跃视图），不影响核心图有界性（铁律一不受影响——T 截断的是工具喂 LLM 的素材，非活跃视图渲染）。

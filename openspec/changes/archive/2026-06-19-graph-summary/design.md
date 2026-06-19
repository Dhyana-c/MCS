# Design: graph-summary

## 决策 1：摘要存储位置——图级 meta（B1），不进节点活跃视图

**选项：**
- B1：MCS store 图级 meta kv（`get/set_graph_meta`），摘要属于图、随图持久化。
- B2：`mcs_agent` 侧 sidecar 缓存，不动核心 store。

**选 B1。** 摘要本质是"这张图的元数据"，语义上属于图、应随图持久化；多入口 / 多 agent 共享同一张图时共享摘要；B2 把"图的属性"错放成"agent 缓存"，未来多入口共享时仍需回迁。代价是动核心 store schema（新增 meta 表），按核心代码规范走 spec + 全测试。

**为何不进 `__seed_root__.content`**：`root.content` 被铁律一口径（`ContextRenderer.render_node_full`）算进 root 的活跃双向视图 token，而 `fanout_reducer._has_budget_pressure` 检查 root——摘要会挤占 root 的层级预算。图级 meta 是**非节点字段**，不进任何节点的活跃视图渲染 / 估算口径 → **不触碰核心不变量**。`root.extensions["summary"]` 同理不可行（content 空时 `render_node_full` 回退 summary 当 body，仍进 token）。

## 决策 2：摘要插件用 CompactionPluginInterface（契约驱动，非语义偏好）

**选项：**
- `CompactionPluginInterface`（COMPACTION）：`should_run(changed_nodes, store)` + `run(changed_nodes, store, llm_caller)`，write pipeline 阶段⑥每次 learn 后自动调度（`write_pipeline._run_compaction`，阶段⑤关系边已落库、阶段⑦落盘前）。
- `MaintenanceInterface`（MAINTENANCE）：`run(store)` + `should_run()`（无参），语义为周期性后台 GC。

**选 CompactionPluginInterface。** 这是契约驱动：
- 摘要生成**需要 `llm_caller`**（LLM 归纳）——仅 COMPACTION 接口注入；MAINTENANCE 的 `run(store)` 无 llm_caller。
- 摘要要 **learn 后触发**（基于 `changed_nodes` 判新概念）——COMPACTION 在阶段⑥每次 ingest 后跑；MAINTENANCE 是周期性、无 changed_nodes。
- 摘要要在**落盘前**生成（随阶段⑦持久化）——COMPACTION 正在⑥、⑦之前。

> 附注：write pipeline 阶段⑥现称"compaction"，实质是"learn 后维护钩子"，fanout（重组）与本插件（摘要）均为"learn 后维护"。语义命名债务不在本 change 范围。

## 决策 3：每次 learn 刷新

每次 ingest 后阶段⑥触发摘要归纳。learn 本为重操作（含多轮 LLM），增量一次归纳可接受。不做节流（保持简单；若未来 learn 频次极高再议）。

## 决策 4：≤ 1k token，两道闸

- `GRAPH_SUMMARY_TOKEN_BUDGET`（默认 1000 token，口径与 LLM 一致；中文约 600-700 汉字，足够写主题 + 范围 + 顶层领域）。
- 第一道：归纳 prompt 明确要求 LLM 输出 ≤ 预算。
- 第二道：`chat()` 喂 prompt 前校验 / 截断，防 LLM 超标摘要进入 agent 上下文。
- 进 system（messages[0]）一次性付，不随 ReAct 轮次累加。
- **命名映射**：spec 的 `GRAPH_SUMMARY_TOKEN_BUDGET` 为预算概念（默认 1000）；实现中归纳插件用 `max_tokens` 配置、`MemoryAgent` 用 `summary_budget` 参数（均默认 1000 字，与 `gen_summary` 口径一致）。

## 决策 5：归纳对象 = 顶层 hub，必须 LLM 语义

- 归纳输入 = `__seed_root__` 的层级子（顶层 hub，经 fanout 收敛的组织中心）的 name+content，**非全图**（全图过大、hub 层已是语义收敛点）。图极小时（root 下直挂概念）归纳这些概念。
- **归纳必须 LLM 语义**（呼应铁律二），禁止机械拼接 / 空洞聚合标签（如"综合信息枢纽"）。

## 决策 6：摘要用 MCS 核心 LLM 生成、agent LLM 消费

- 生成经 compaction 插件注入的 `llm_caller`（= write pipeline 的 MCS 核心 LLM）——摘要属于图、用建图的 LLM 生成，语义自洽。
- 消费由 agent LLM（`mcs_agent` 自有 LLM）每轮读 system prompt。两 LLM 分工与现有架构一致（agent LLM 独立于 MCS read_llm）。

## 决策 7：失败隔离

摘要归纳失败（LLM 异常 / 超时）MUST 隔离为日志、不阻塞 ingest、保留旧摘要（无旧摘要则 meta 维持空）。agent 取到空摘要时 system prompt「当前记忆图主题」段降级为占位（如"(尚未生成)"），路由仍按其余规则工作。

## 决策 8：路由 prompt 改写边界（仍 100% 交 LLM、无代码分流）

改写 `DEFAULT_SYSTEM_PROMPT` 补三段，**不改 ReAct loop 机制**（路由仍全交 LLM、无 if-else 分流）：
- 「何时直接回答」：闲聊 / 通用知识 / 常识推理 / 计算 / 写作等不依赖记忆的，直接答。
- 「探索策略」：search 返回空或 associate 无相关时，最多换 1-2 种切入，仍无果据实说明、不臆造。
- 「记忆诚实」：对记忆类问题不臆造；过渡态约束——不假装记得本轮之前的对话（会话历史将由后续事件节点 change 承载）。

此改动触及 `memory-agent` spec「系统提示词导航导向」契约，走 spec delta。

## 决策 9：LLM purpose 注册 + 默认插件列表接入（实现期细化）

代码精读暴露两个 proposal 未覆盖的接入点（方向不变、补漏）：

1. **`llm_caller` 按 purpose 查 prompt**：`llm_caller` = `write_llm.call`，`call()` 经 `get_prompt(purpose)` 从 `mcs/prompts/DEFAULT_PROMPTS` 查 `PromptBundle`（`llm.py:213-224`），未注册抛 `KeyError`。节点级 `gen_summary` 已注册；图级摘要 prompt 逻辑不同（多 hub → 一段图主题），**新 purpose `gen_graph_summary` + 新 PromptBundle**（`parse` 返回 str）。

2. **插件启用由 `config.write_plugins` 决定、非注册表**：`PHASE1_WRITE_PLUGINS`（`config.py:23`）= `[fanout_reducer, summary_regen]`，`knowledge_graph()` 用它。注册表（`phase1.py`）只做"名字→类"映射。故 `graph_summary` 须**同时**进注册表与 `PHASE1_WRITE_PLUGINS` 才默认每次 learn 跑——这与"每次 learn 刷新"决策一致（用户既定）。影响面：所有 Phase1 build 的每次 ingest +1 次图摘要 LLM 归纳（spec 所要）。

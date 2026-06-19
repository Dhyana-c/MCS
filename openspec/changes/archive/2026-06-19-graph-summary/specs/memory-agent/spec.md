## MODIFIED Requirements

### Requirement: 系统提示词导航导向

`MemoryAgent` 默认 system_prompt SHALL 指导 LLM 在"直接作答"与"工具探索记忆图"间自主判断，而非无条件调用工具：

- **何时直接回答（不调工具）**：闲聊 / 问候 / 身份询问；通用知识、常识、推理、计算、写作等不依赖个人记忆的内容；自身能力足以准确作答时。
- **何时探索记忆图（调工具）**：仅当问题依赖"已记下来的东西"（用户曾 learn 或图里的事实 / 关系）。
- **探索策略**：search 返回空或 associate 无相关时，最多换 1-2 种切入（如 keyword 失败改 direct），仍无果据实说明"记忆里没有"、不臆造。
- **记忆诚实**：对记忆类问题不臆造；**不假装记得本轮之前的对话**（会话历史将由图内事件节点承载，当前为过渡态）。

导航决策权仍交给 LLM：选哪个工具、哪个种子、哪种模式、哪两个节点均由 LLM 决定。

#### Scenario: 直接答路径有引导

- **WHEN** 构造 `MemoryAgent`
- **THEN** 默认 system_prompt MUST 含"何时直接回答（不调工具）"的判断标准
- **AND** MUST 含"记忆诚实 / 不假装记得上文"的过渡态约束

#### Scenario: 探索路径保留

- **WHEN** 默认 system_prompt 指导探索
- **THEN** MUST 保留 5 工具（learn / search / associate / reason / recall）说明与跨工具 id 引用规则

---

## ADDED Requirements

### Requirement: 图级摘要注入 agent system prompt

`MemoryAgent.chat()` SHALL 在每轮对话开头取最新图级摘要（`MemoryStore.graph_summary()`）并注入 system prompt 的「当前记忆图主题」段，使 LLM 能据图主题判断问题是否可能属于记忆范围。注入前 SHALL 对摘要做 ≤ `GRAPH_SUMMARY_TOKEN_BUDGET` 校验 / 截断（防归纳超标进入上下文）。摘要为空时该段降级为占位（如"(尚未生成)"），路由按其余规则工作。

#### Scenario: 每轮注入最新摘要

- **WHEN** 调用 `chat(msg)` 且图级摘要非空
- **THEN** messages 的 system 内容 MUST 含当前摘要文本

#### Scenario: 空摘要降级

- **WHEN** 图级摘要为空（尚未生成）
- **THEN** system 的主题段 MUST 降级为占位，MUST NOT 抛异常

#### Scenario: 超标摘要截断

- **WHEN** 取得的摘要超 `GRAPH_SUMMARY_TOKEN_BUDGET`
- **THEN** 注入前 MUST 截断至 ≤ 预算

---

### Requirement: MemoryStore.graph_summary 原语

`MemoryStore.graph_summary() -> str` SHALL 经单 worker 线程读图级 meta（`get_graph_meta("graph_summary")`），返回摘要文本；无摘要返回空串。调用方线程 MUST NOT 直接读 store（线程安全铁律，同其他原语）。

#### Scenario: 取摘要

- **WHEN** 图级 meta 含摘要
- **THEN** `graph_summary()` MUST 返回该文本

#### Scenario: 无摘要返回空串

- **WHEN** 图级 meta 无 "graph_summary" key
- **THEN** `graph_summary()` MUST 返回 ""

#### Scenario: 经 worker 线程

- **WHEN** 调用 `graph_summary()`
- **THEN** MUST 经 `ThreadPoolExecutor(max_workers=1)` 执行（同其他原语）

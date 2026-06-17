# memory-agent Specification

## Purpose
TBD - created by archiving change memory-agent-skeleton. Update Purpose after archive.
## Requirements
### Requirement: MemoryStore 单线程包装 MCS

`MemoryStore` SHALL 在单一 worker 线程内构造 MCS 并执行其全部调用，规避 MCS 非线程安全与 SQLite 线程亲和。

#### Scenario: 所有 MCS 调用经同一 worker 线程

- **WHEN** 多次并发调用 `MemoryStore.query` / `MemoryStore.ingest`
- **THEN** 每次 MUST 经 `ThreadPoolExecutor(max_workers=1)` 串行执行
- **AND** 调用方线程 MUST NOT 直接触碰 MCS 实例

#### Scenario: query 返回 LLM 可读文本

- **WHEN** 调用 `MemoryStore.query(query)`
- **THEN** MUST 在 worker 线程内执行 `mcs.query` 并经渲染纯函数返回文本

---

### Requirement: MemoryStore 复用 mcp-server 渲染纯函数

`MemoryStore` SHALL 复用 `mcs.mcp.server._render_query_result` 与 `_format_ingest_status` 渲染结果，不重复实现。

#### Scenario: 复用而非重复实现

- **WHEN** `MemoryStore` 渲染 query / ingest 结果
- **THEN** MUST 调用 mcp-server 的渲染纯函数
- **AND** MUST NOT 自行实现等价渲染逻辑

---

### Requirement: MemoryAgent ReAct loop

`MemoryAgent` SHALL 通过 LLM tool calling 执行 ReAct 循环：LLM 返回 `tool_calls` 时执行工具并把结果回灌为 `tool` 消息；无 `tool_calls` 时返回最终答复文本；达到 `max_turns` 回退为兜底文本。

#### Scenario: 无工具调用直接答复

- **WHEN** LLM 返回无 `tool_calls` 的 assistant 消息
- **THEN** `chat()` MUST 返回该消息的 `content`

#### Scenario: 工具调用结果回灌

- **WHEN** LLM 返回 `tool_calls`
- **THEN** MUST 执行每个工具调用
- **AND** MUST 将结果作为 `tool` 消息（带 `tool_call_id`）追加到消息历史
- **AND** MUST 继续下一轮 LLM 调用

#### Scenario: 达到最大轮次回退

- **WHEN** 循环达到 `max_turns` 仍未给出最终答复
- **THEN** `chat()` MUST 返回兜底文本，MUST NOT 抛出异常

---

### Requirement: 单次工具异常隔离

单次工具调用抛出的异常 SHALL 被隔离为 `[error]` 文本回灌，不中断 ReAct loop。

#### Scenario: 工具异常不毁 loop

- **WHEN** 某次工具调用抛异常
- **THEN** MUST 将异常转为 `[error] {类型}: {信息}` 文本
- **AND** loop MUST 继续执行（不向调用方抛异常）

#### Scenario: 非法 JSON 参数

- **WHEN** 工具调用的 `arguments` 不是合法 JSON
- **THEN** MUST 返回 `[error] 工具参数不是合法 JSON`，不抛异常

---

### Requirement: LLM 调用可注入

`MemoryAgent` SHALL 接受 `llm_call(messages, tools) -> assistant_dict` 可注入 callable，而非绑定具体 LLM SDK。

#### Scenario: 测试注入 mock

- **WHEN** 测试构造 `MemoryAgent(memory, scripted_llm_call)`
- **THEN** loop MUST 使用注入的 callable，不依赖真实 LLM API

---

### Requirement: 记忆工具集（memory_query / memory_ingest）

`MemoryAgent` SHALL 经 `MEMORY_TOOLS` 向 LLM 暴露两个工具：`memory_query(query)`（查记忆图谱）、`memory_ingest(text)`（写记忆图谱），分发到 `memory.query` / `memory.ingest`。

> 注：本工具集为应用骨架版本；细粒度导航工具体系（learn/search/associate/reason/recall）由后续 `memory-agent-navigation` 提案演进。

#### Scenario: 分发到 memory 方法

- **WHEN** LLM 调用 `memory_query` / `memory_ingest`
- **THEN** MUST 分别转发到 `memory.query` / `memory.ingest`

#### Scenario: 未知工具

- **WHEN** LLM 调用不在工具表中的工具名
- **THEN** MUST 返回 `[error] 未知工具：{name}`

---

### Requirement: FastAPI 对话后端

`create_app(agent)` SHALL 提供对话后端：`POST /chat`（`{message}` → `{reply}`）、`GET /health`（`{ok: true}`）、CORS 中间件、静态前端挂载。

#### Scenario: 可注入任意 agent

- **WHEN** 调用 `create_app(fake_agent)`，其中 fake_agent 暴露 `chat(str) -> str`
- **THEN** `/chat` MUST 转发到 `fake_agent.chat` 并返回其结果

#### Scenario: 缺字段请求被拒

- **WHEN** POST `/chat` 未提供 `message` 字段
- **THEN** MUST 返回 422

#### Scenario: agent 异常返回 500

- **WHEN** agent.chat 抛异常
- **THEN** MUST 返回 500，不重抛给测试客户端

#### Scenario: 根路径服务前端

- **WHEN** GET `/`
- **THEN** MUST 返回 `index.html`（content-type 含 text/html）

---

### Requirement: 环境变量构建生产 agent

`build_agent_from_env()` SHALL 从 `MCS_CONFIG`（yaml 路径）、`AGENT_LLM_API_KEY`、`AGENT_LLM_MODEL`、（可选）`AGENT_LLM_BASE_URL` 构建生产 `MemoryAgent`；缺关键变量时以非零码早失败。

#### Scenario: 缺 MCS_CONFIG 早失败

- **WHEN** 未设 `MCS_CONFIG`
- **THEN** MUST 抛 `SystemExit`（非零）

#### Scenario: 缺 API key 早失败

- **WHEN** 设了 `MCS_CONFIG` 但未设 `AGENT_LLM_API_KEY`
- **THEN** MUST 抛 `SystemExit`（非零）

---

### Requirement: 启动入口

`python -m mcs.agent` SHALL 构建生产 agent 并启动 uvicorn（默认 127.0.0.1:8000）。

#### Scenario: 模块入口可启动

- **WHEN** 执行 `python -m mcs.agent`
- **THEN** MUST 调用 `app.run()`（uvicorn 惰性 import）

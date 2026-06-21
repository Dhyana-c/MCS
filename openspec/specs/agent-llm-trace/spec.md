## ADDED Requirements

### Requirement: LLM 调用追踪数据结构

`mcs_agent/trace.py` SHALL 定义三个 dataclass：

- `LLMCallTrace`：记录单次 LLM 调用。字段：`model: str`、`latency_ms: float`、`token_usage: TokenUsage | None`（含 `prompt_tokens` / `completion_tokens` / `total_tokens`）、`timestamp: float`（`time.time` 墙钟时间）、`request_summary: list[MessageSummary]`（每条消息 `role` + `content[:100]`）、`response_summary: str`（`content[:200]`）、`tool_call_names: list[str]`（LLM 请求的工具名列表）
- `ToolCallTrace`：记录单次工具调用。字段：`tool_name: str`、`args_summary: str`（参数 JSON 的 `[:200]`）、`result_summary: str`（返回文本 `[:200]`）、`latency_ms: float`、`error: str | None`（异常信息，无异常时为 None）
- `ChatTrace`：记录一次完整 chat 链路。字段：`user_message: str`（用户输入 `[:100]`）、`reply: str`（最终答复 `[:200]`）、`llm_calls: list[LLMCallTrace]`、`tool_calls: list[ToolCallTrace]`、`total_latency_ms: float`、`total_tokens: int | None`（所有 LLM 调用的 token 总和，任一缺失时为 None）

#### Scenario: 数据结构完整性

- **WHEN** 构造 `ChatTrace`
- **THEN** MUST 包含该次 chat 的所有 LLM 调用和工具调用记录
- **AND** `total_latency_ms` MUST 为从 `chat()` 入口到返回的墙钟时间
- **AND** `total_tokens` MUST 为所有 `LLMCallTrace.token_usage.total_tokens` 之和（任一为 None 时整体为 None）

#### Scenario: 摘要截断

- **WHEN** LLM 响应 content 或工具返回文本超过摘要上限
- **THEN** MUST 截断至上限长度（`response_summary[:200]`、`result_summary[:200]`），MUST NOT 存完整内容

---

### Requirement: llm_call 内部提取 token 用量和延迟

`make_openai_llm_call` 返回的 callable SHALL 从 OpenAI SDK 响应对象提取 `usage` 字段和调用延迟，构造 `LLMCallTrace` 并附加到返回 dict 的 `_trace` 键。

#### Scenario: 提取 token usage

- **WHEN** OpenAI SDK 响应含 `usage` 字段（非 None）
- **THEN** 返回 dict 的 `_trace` 键 MUST 包含 `LLMCallTrace`，其中 `token_usage` 为实际值

#### Scenario: usage 字段缺失

- **WHEN** OpenAI SDK 响应的 `usage` 为 None 或不存在
- **THEN** `LLMCallTrace.token_usage` MUST 为 None，MUST NOT 崩溃

#### Scenario: 延迟记录

- **WHEN** `llm_call` 执行
- **THEN** `LLMCallTrace.latency_ms` MUST 记录从调用开始到响应返回的毫秒数（`time.perf_counter`）

#### Scenario: mock llm_call 无 trace

- **WHEN** 注入的 mock `llm_call` 返回的 dict 不含 `_trace` 键
- **THEN** `loop.py` MUST 将 `LLMCallTrace` 的各字段置为默认/None 值，MUST NOT 崩溃

---

### Requirement: _trace 键剥离

`loop.py` 将 LLM 返回的 `assistant` dict 追加到 `messages` 列表前 SHALL 剥离 `_trace` 键，防止内部元数据泄露到 LLM 消息历史。

#### Scenario: 追加前剥离

- **WHEN** `llm_call` 返回的 dict 含 `_trace` 键
- **THEN** 追加到 `messages` 的 dict MUST NOT 含 `_trace` 键
- **AND** `_trace` 中的 `LLMCallTrace` MUST 被提取到 `ChatTrace.llm_calls`

#### Scenario: 无 _trace 键时不崩溃

- **WHEN** 返回的 dict 不含 `_trace` 键（如 mock）
- **THEN** MUST 跳过 trace 提取，正常执行

---

### Requirement: MemoryAgent.chat 构造 ChatTrace 并回调

`MemoryAgent.chat()` SHALL 构造 `ChatTrace` 聚合该次对话的所有 LLM 调用和工具调用记录，并在 `chat()` 返回前调用 `on_trace(chat_trace)` 回调（如果非 None）。

#### Scenario: 完整 chat 追踪

- **WHEN** 一次 `chat()` 执行了 N 次 LLM 调用和 M 次工具调用
- **THEN** 构造的 `ChatTrace` MUST 含 N 条 `llm_calls` 和 M 条 `tool_calls`
- **AND** `total_latency_ms` MUST 为整个 `chat()` 的墙钟耗时

#### Scenario: 回调异常隔离

- **WHEN** `on_trace` 回调抛出异常
- **THEN** 异常 MUST 被隔离为 `logger.warning`，MUST NOT 影响 `chat()` 的正常返回值

#### Scenario: 无回调时静默

- **WHEN** `MemoryAgent` 未设置 `on_trace`（默认 None）
- **THEN** `chat()` MUST 正常工作，MUST NOT 产生任何副作用

---

### Requirement: 工具调用追踪

`MemoryAgent._dispatch()` SHALL 记录每次工具调用的 `ToolCallTrace`，包括工具名、参数摘要、返回摘要、延迟、异常信息。

#### Scenario: 正常工具调用

- **WHEN** 工具调用正常返回
- **THEN** `ToolCallTrace.error` MUST 为 None
- **AND** `ToolCallTrace.result_summary` MUST 为返回文本的 `[:200]`

#### Scenario: 工具调用异常

- **WHEN** 工具调用抛出异常
- **THEN** `ToolCallTrace.error` MUST 为 `"{类型}: {信息}"` 格式
- **AND** `ToolCallTrace.result_summary` MUST 为 `"[error] ..."` 格式（与当前错误文本一致）

#### Scenario: 非法 JSON 参数

- **WHEN** 工具调用的 `arguments` 不是合法 JSON
- **THEN** `ToolCallTrace.error` MUST 记录此情况
- **AND** 异常隔离行为 MUST 不变（返回 `[error]` 文本，不中断 loop）

---

### Requirement: 结构化日志输出 ChatTrace

`create_app()` SHALL 为 `MemoryAgent` 配置 `on_trace` 回调，使用 `logging.info` + `dataclasses.asdict()` 输出结构化 trace 日志。

#### Scenario: trace 日志输出

- **WHEN** 一次 `chat()` 完成
- **THEN** MUST 通过 `logging.info` 输出包含 `ChatTrace` 全部字段的日志条目
- **AND** 日志 MUST 可被 JSON formatter 解析

#### Scenario: 不影响响应

- **WHEN** trace 日志输出耗时或失败
- **THEN** MUST NOT 影响 `/chat` API 的响应时间和正确性

## MODIFIED Requirements

### Requirement: LLM 调用可注入

`MemoryAgent` SHALL 接受 `llm_call(messages, tools) -> assistant_dict` 可注入 callable，而非绑定具体 LLM SDK。`llm_call` 返回的 dict MAY 含 `_trace` 键（内部元数据），`MemoryAgent` SHALL 在追加到 `messages` 前剥离 `_trace` 键。

#### Scenario: 测试注入 mock

- **WHEN** 测试构造 `MemoryAgent(memory, scripted_llm_call)`
- **THEN** loop MUST 使用注入的 callable，不依赖真实 LLM API
- **AND** mock 返回的 dict 不含 `_trace` 键时 MUST 正常工作

#### Scenario: 生产 llm_call 含 _trace

- **WHEN** `make_openai_llm_call` 返回的 dict 含 `_trace` 键
- **THEN** `MemoryAgent` MUST 提取 trace 数据并剥离 `_trace` 键
- **AND** 追加到 `messages` 的 assistant dict MUST NOT 含 `_trace` 键

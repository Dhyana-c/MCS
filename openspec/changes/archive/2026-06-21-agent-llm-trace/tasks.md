## 1. 追踪数据结构

- [x] 1.1 新建 `mcs_agent/trace.py`，定义 `TokenUsage` dataclass（`prompt_tokens` / `completion_tokens` / `total_tokens`，均可 None）
- [x] 1.2 定义 `MessageSummary` dataclass（`role: str` + `content_preview: str`，截断 100 字符）
- [x] 1.3 定义 `LLMCallTrace` dataclass（`model` / `latency_ms` / `token_usage` / `timestamp` / `request_summary` / `response_summary` / `tool_call_names`）
- [x] 1.4 定义 `ToolCallTrace` dataclass（`tool_name` / `args_summary` / `result_summary` / `latency_ms` / `error`）
- [x] 1.5 定义 `ChatTrace` dataclass（`user_message` / `reply` / `llm_calls` / `tool_calls` / `total_latency_ms` / `total_tokens`），含 `total_tokens` 计算逻辑（任一 LLM trace 缺 token_usage 则整体 None）

## 2. llm_call 包装追踪

- [x] 2.1 修改 `mcs_agent/llm.py`：`make_openai_llm_call` 返回的 callable 内部用 `time.perf_counter` 计延迟、从 `resp.usage` 提取 token 用量、构造 `LLMCallTrace` 并附加到返回 dict 的 `_trace` 键
- [x] 2.2 处理 `usage` 为 None 的场景（`TokenUsage` 各字段置 None）
- [x] 2.3 构造 `request_summary`：遍历 messages，每条取 `role` + `content[:100]`
- [x] 2.4 构造 `response_summary`：取 `content[:200]` + `tool_calls` 名称列表

## 3. loop.py 集成追踪

- [x] 3.1 `MemoryAgent.__init__` 新增 `on_trace` 可选参数
- [x] 3.2 `chat()` 入口记录起始 `time.perf_counter`，出口构造 `ChatTrace` 并调用 `on_trace`
- [x] 3.3 每轮 `llm_call` 后从返回 dict 提取 `_trace`（`LLMCallTrace`），追加到 `ChatTrace.llm_calls`；剥离 `_trace` 键后再追加 assistant dict 到 `messages`
- [x] 3.4 `_dispatch()` 内部用 `time.perf_counter` 计延迟、构造 `ToolCallTrace`，追加到 `ChatTrace.tool_calls`；异常时记录 `error` 字段
- [x] 3.5 `on_trace` 回调异常隔离（try/except + logger.warning）

## 4. app.py 结构化日志输出

- [x] 4.1 `create_app()` 中为 `MemoryAgent` 配置 `on_trace` 回调：`logging.info` + `dataclasses.asdict(chat_trace)`
- [x] 4.2 `build_agent_from_env()` 传递 `on_trace` 参数到 `MemoryAgent`

## 5. 测试

- [x] 5.1 测试 `trace.py` 数据结构：构造 `ChatTrace`、验证 `total_tokens` 聚合逻辑（含/缺 token_usage 两种场景）
- [x] 5.2 测试 `llm.py`：mock OpenAI 响应含/不含 `usage`，验证 `_trace` 键内容
- [x] 5.3 测试 `loop.py`：注入 mock `llm_call`（无 `_trace`），验证 `ChatTrace` 的 `llm_calls` / `tool_calls` 完整性
- [x] 5.4 测试 `_trace` 键剥离：验证追加到 `messages` 的 dict 不含 `_trace` 键
- [x] 5.5 测试 `on_trace` 回调异常隔离：回调抛异常时 `chat()` 仍正常返回
- [x] 5.6 测试 `on_trace=None` 时静默无副作用

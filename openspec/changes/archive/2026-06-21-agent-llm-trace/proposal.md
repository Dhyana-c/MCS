## Why

mcs_agent 当前仅用 2 处 `logger.warning` 做异常记录，没有任何结构化的 LLM 调用追踪。每次 `llm_call` 的输入输出、延迟、token 用量、工具调用链路完全不可观测——调试靠 print，性能瓶颈靠猜，成本靠账单事后看。对于一个 ReAct 循环内可能多次调用 LLM + 多次工具分发的 agent，缺少调用链路追踪意味着：无法定位哪轮 LLM 调用慢、哪个工具拖后腿、一次对话消耗了多少 token / 金钱。

## What Changes

- 新增 `mcs_agent/trace.py`：轻量调用链路追踪模块，记录每次 LLM 调用和工具调用的完整生命周期
- `LLMCallTrace` 数据类：捕获单次 LLM 调用的 model / messages 摘要 / 响应摘要 / 延迟 / token 用量 / 时间戳
- `ToolCallTrace` 数据类：捕获单次工具调用的工具名 / 参数 / 返回摘要 / 延迟 / 异常
- `ChatTrace` 数据类：聚合一次 `chat()` 完整链路（用户消息 → 多轮 LLM + 工具调用 → 最终答复）
- `MemoryAgent.chat()` 每次执行产出一个 `ChatTrace`，通过回调 `on_trace` 暴露给调用方
- `llm_call` 包装：`make_openai_llm_call` 返回的 callable 内部记录调用延迟和 token 用量（从 OpenAI 响应对象提取 `usage` 字段）
- `create_app` 将 `ChatTrace` 通过结构化日志（`logging` JSON formatter）输出；后续可接文件 / 外部观测系统

## Capabilities

### New Capabilities
- `agent-llm-trace`: mcs_agent 的 LLM 调用链路追踪——结构化记录每次 LLM 调用、工具调用、完整 chat 链路

### Modified Capabilities
- `memory-agent`: `MemoryAgent.chat()` 新增 `on_trace` 回调参数；`make_openai_llm_call` 返回的 callable 内部提取 token 用量

## Impact

### 代码变更
- `mcs_agent/trace.py`: **新增**，定义 `LLMCallTrace` / `ToolCallTrace` / `ChatTrace` 数据类
- `mcs_agent/llm.py`: `make_openai_llm_call` 返回的 callable 内部提取 `resp.usage` 记录 token 用量
- `mcs_agent/loop.py`: `MemoryAgent.chat()` 构造 `ChatTrace` 并回调 `on_trace`
- `mcs_agent/app.py`: `create_app` 配置结构化日志输出 `ChatTrace`

### API 变更
- `MemoryAgent.__init__` 新增可选参数 `on_trace: Callable[[ChatTrace], None] | None = None`，**非 breaking**
- `make_openai_llm_call` 返回的 callable 签名不变（仍是 `(messages, tools) -> dict`），但返回的 dict 新增 `_trace` 键（内部约定，不影响 LLM 消息格式）

### 依赖
- 无新外部依赖（`dataclasses` + `logging` + `time` 均为标准库）
- 前置：无（独立变更）

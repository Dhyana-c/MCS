## Context

mcs_agent 的 ReAct 循环（`loop.py`）在一次 `chat()` 调用中可能执行多轮 LLM 调用 + 多次工具调用，但当前仅有 2 处 `logger.warning`，无任何结构化追踪。

```
用户消息 → chat()
  ├─ 轮 1: llm_call(messages, tools)  ← 无记录
  │   ├─ tool_call: search(query)     ← 无记录
  │   └─ tool_call: associate(id)     ← 无记录
  ├─ 轮 2: llm_call(messages, tools)  ← 无记录
  │   └─ tool_call: learn(text)       ← 无记录
  └─ 轮 3: llm_call(messages, tools)  ← 无记录
      └─ 最终答复                      ← 无记录
```

关键约束：
- `llm_call` 签名为 `(messages, tools) -> dict`，是可注入的 callable——不能改签名
- OpenAI SDK 的 `chat.completions.create` 响应含 `usage` 字段（`prompt_tokens` / `completion_tokens` / `total_tokens`），但当前 `llm_call` 丢弃了
- `MemoryAgent` 可被测试注入 mock `llm_call`，追踪不能破坏这个可测试性
- mcs_agent 是独立顶层包，不引入重型依赖（如 OpenTelemetry）

## Goals / Non-Goals

**Goals:**
- 结构化记录每次 `llm_call` 的输入摘要、输出摘要、延迟、token 用量
- 结构化记录每次工具调用的工具名、参数摘要、返回摘要、延迟、异常
- 聚合一次 `chat()` 的完整链路为 `ChatTrace`，通过回调暴露
- 保持 `llm_call` 签名不变、保持可注入可测试
- 零外部依赖（标准库 dataclasses + logging + time）

**Non-Goals:**
- 不做分布式追踪（无 OpenTelemetry / Jaeger / Zipkin 集成）
- 不做持久化存储（trace 仅在回调中输出，不写数据库）
- 不做实时仪表盘 / Web UI 展示
- 不改 MCS 核心（`mcs/` 包）的 LLM 调用追踪——那是 `model-aware-token-estimation` 的范畴
- 不做采样率控制（全量记录，agent 单次 chat 的 LLM 调用数有限）

## Decisions

### D1: 追踪数据结构用 dataclass 而非 dict

**选择**：`LLMCallTrace` / `ToolCallTrace` / `ChatTrace` 为 `@dataclass`。

**替代方案**：普通 dict（更灵活但无类型约束、IDE 不补全）。Python 3.10+ dataclass 足够轻量，类型安全收益更大。

### D2: LLM 调用追踪通过包装 llm_call 实现，不改签名

**选择**：`make_openai_llm_call` 返回的 callable 内部提取 `resp.usage` 和延迟，将 trace 附加到返回 dict 的 `_trace` 键。`loop.py` 侧用 `_extract_llm_trace()` 辅助函数取 trace。

**替代方案**：改 `llm_call` 签名为 `(messages, tools) -> (dict, LLMCallTrace)`——破坏所有调用方和 mock。不可接受。

**替代方案**：用线程局部变量 / context var 传递 trace——隐式传递，测试不透明。不选。

**`_trace` 键约定**：以 `_` 前缀标识为内部元数据，LLM 消息历史不应序列化此键。`loop.py` 追加 `assistant` dict 到 `messages` 前，先剥离 `_trace` 键。

### D3: ChatTrace 通过回调暴露，不污染 chat() 返回值

**选择**：`MemoryAgent.__init__` 新增 `on_trace: Callable[[ChatTrace], None] | None = None`。`chat()` 结束时调用 `on_trace(chat_trace)`（如果非 None）。

**替代方案**：`chat()` 返回 `(reply, ChatTrace)` 元组——破坏所有调用方。不可接受。

**替代方案**：`ChatTrace` 存 `self.last_trace`——并发下会覆盖。回调更灵活。

### D4: 消息摘要而非完整内容

**选择**：trace 中不存完整 messages（可能巨大），存摘要：
- `messages` 摘要：每条消息的 `role` + `content[:100]`
- LLM 响应摘要：`content[:200]` + `tool_calls` 名称列表
- 工具调用结果摘要：`result[:200]`

**替代方案**：存完整内容——调试方便但内存暴涨、日志膨胀。摘要够定位问题。

### D5: 延迟用 time.perf_counter 而非 time.time

**选择**：`time.perf_counter()` 测量单次调用延迟（单调递增、最高精度、不受系统时钟调整影响）。

### D6: 结构化日志输出

**选择**：`app.py` 中 `on_trace` 回调用 `logging.info` + `dataclasses.asdict(chat_trace)` 输出 JSON 格式的 trace。后续接文件 / 外部系统时只需换 formatter。

**替代方案**：直接 `print(json.dumps(...))`——不灵活、不分级。不选。

## Risks / Trade-offs

- **`_trace` 键泄露到 LLM 消息历史** → `loop.py` 追加 `assistant` dict 到 `messages` 前，必须剥离 `_trace` 键。若遗漏，LLM API 可能因未知字段报错或忽略——需在测试中覆盖此场景
- **OpenAI 兼容后端不返回 `usage`** → `usage` 字段为 `None` 时 `LLMCallTrace.token_usage` 留 None，不崩溃。trace 中缺失 token 数据是可接受的（延迟数据仍有价值）
- **回调异常影响 chat** → `on_trace` 回调中的异常必须被隔离（try/except + logger.warning），绝不能让追踪逻辑的失败破坏正常对话
- **摘要截断丢失信息** → 100/200 字符的摘要可能不够定位复杂问题。这是有意的取舍：调试时需要完整内容应直接看 LLM 请求/响应（另开 debug 日志），trace 侧重链路概览和性能指标

## ADDED Requirements

### Requirement: OllamaLLMPlugin 实现统一 LLMInterface

The system SHALL provide `OllamaLLMPlugin` implementing `LLMInterface`. Its ONLY vendor-specific responsibility is `_raw_call(system: str, user: str) -> str` via Ollama's native `/api/chat` endpoint. Rendering, prompt assembly, and parsing MUST be inherited from the `LLMInterface.call` base implementation — the plugin MUST NOT override `call`.

#### Scenario: 插件接口契约

- **WHEN** 检查 `OllamaLLMPlugin` 类
- **THEN** `name` MUST == `"ollama_llm"`；`interfaces` MUST 含 `LLMInterface`；MUST 实现 `_raw_call(system, user) -> str`

#### Scenario: 复用基类编排

- **WHEN** 框架对 `OllamaLLMPlugin` 发起 `call(purpose, nodes_in, free_args)`
- **THEN** 调用 MUST 走 `LLMInterface.call` 的统一 5 步（查 prompt → 渲染 → 组装 → `_raw_call` → parse）；`OllamaLLMPlugin` MUST NOT 自定义这套编排

---

### Requirement: 厂商插件零 prompt 模板

`OllamaLLMPlugin` source MUST NOT contain any prompt template strings or business semantics. All prompt material MUST live under `mcs/prompts/`.

#### Scenario: 源码无 prompt 字符串

- **WHEN** 审查 `mcs/plugins/phase1/ollama_llm.py`
- **THEN** 该文件 MUST NOT 含 "你是" / "extract" / "判断" 等 prompt 关键短语；MUST NOT 含模板 placeholder `{name}` / `{content}` 等

#### Scenario: 换后端不动业务

- **WHEN** 用户把后端从 DeepSeek 切换为 Ollama
- **THEN** 仅需在配置中以 `ollama_llm` 替换 `deepseek_llm`（或用 `MCSConfig.knowledge_graph(llm="ollama")`）；MUST NOT 改动 `mcs/prompts/` 或 `mcs/core/` 任何文件

---

### Requirement: 配置键与本地默认

`OllamaLLMPlugin` SHALL accept config keys: `base_url`, `model`, `timeout`, `max_tokens`, `num_ctx`, `think`, `api_key`. `base_url` SHALL default to `http://localhost:11434/v1`（末尾 `/v1` 在推导原生端点时归一为根地址，保持与历史配置兼容）；`timeout` SHALL default to a longer-than-cloud value（本地推理较慢）；`max_tokens` / `num_ctx` SHALL have sane defaults. `think` SHALL default to `False`（思维模型默认关闭 chain-of-thought）。因本地无需鉴权，`api_key` 用占位字符串即可。

#### Scenario: 默认值

- **WHEN** 配置未提供 `base_url` / `timeout` / `max_tokens` / `num_ctx` / `think`
- **THEN** `base_url` MUST 回退到 `http://localhost:11434/v1`；`timeout` MUST 取较长的内置默认；`max_tokens` / `num_ctx` MUST 取内置默认（非 None）；`think` MUST 默认 `False`

#### Scenario: base_url 归一为原生端点

- **WHEN** `base_url` 形如 `http://host:11434/v1`（或带末尾斜杠）
- **THEN** 插件 MUST 把请求发往归一后的根地址 + `/api/chat`（如 `http://host:11434/api/chat`）

#### Scenario: 模型可配置且需先 pull

- **WHEN** 配置提供 `model`（如 `qwen2.5:7b`/`qwen3:8b`）
- **THEN** 插件 MUST 把该 `model` 用于请求；该模型 MUST 由使用者先 `ollama pull`（插件不负责拉取）

---

### Requirement: 原生 /api/chat 调用、think 控制与响应解析

`_raw_call(system, user)` MUST issue a native Ollama `/api/chat` request（`stream=false`）：`system`（非空时）作为一条 `role="system"` 消息、`user` 作为一条 `role="user"` 消息；请求 MUST 携带 `think`（来自配置，默认 `False`）以及 `options.num_predict`（= `max_tokens`）/ `options.num_ctx`（= `num_ctx`）。`_raw_call` MUST 返回 `message.content` 文本（无内容时返回空串）。

之所以走原生端点而非 OpenAI 兼容 `/v1`：只有原生 `/api/chat` 支持 `think` 开关，能对思维模型（qwen3/qwq/deepseek-r1…）关闭冗长的 chain-of-thought——这是 Ollama 后端在这类模型上可用的前提。

#### Scenario: system / user 映射

- **WHEN** `_raw_call("S", "U")` 被调用
- **THEN** 请求体 MUST 含一条 `role="user"` 内容 `"U"`；当 `"S"` 非空时 MUST 另含一条 `role="system"` 内容 `"S"`；MUST 含 `think` 字段与 `options.num_predict` / `options.num_ctx`

#### Scenario: 空 system 不传

- **WHEN** `_raw_call("", "U")`
- **THEN** 请求 MUST NOT 含空的 system 消息；仍含 user 消息

#### Scenario: 默认关闭 thinking

- **WHEN** 配置未显式开启 `think`
- **THEN** 请求体 `think` MUST 为 `False`；当 `think=True` 时 MUST 透传为 `True`

#### Scenario: 返回 message 文本

- **WHEN** Ollama 返回成功的 chat 响应
- **THEN** `_raw_call` MUST 返回 `message.content`（无内容时返回空串）；`message.content` 为空但存在 `message.thinking` 时 MAY 从 thinking 文本兜底提取 JSON

---

### Requirement: 错误处理基线对齐 Phase 1

`OllamaLLMPlugin` SHALL follow the Phase 1 error baseline: any call failure MUST raise `LLMCallError` with no retry; Ollama 未运行或模型未 pull MUST 表现为清晰的 `LLMCallError`。

#### Scenario: 调用失败抛 LLMCallError

- **WHEN** Ollama 请求超时、连接失败或返回非成功状态
- **THEN** 插件 MUST 抛 `LLMCallError`；当前 pipeline 中止；MUST NOT 自动重试

#### Scenario: 未运行 / 模型未 pull 的清晰提示

- **WHEN** Ollama 服务未启动（连不上）或请求的 `model` 未 pull
- **THEN** `_raw_call` MUST 抛 `LLMCallError`，提示启动 `ollama serve` 并 `ollama pull <model>`

---

### Requirement: 可选依赖、惰性导入与默认后端不变

`OllamaLLMPlugin` MUST lazily import its HTTP client (`httpx`) so the plugin class loads even when the client or Ollama is absent. Adding this adapter MUST NOT change the default LLM of `MCSConfig.knowledge_graph()`.

#### Scenario: 惰性导入不阻塞加载

- **WHEN** 环境未安装 `httpx` 或 Ollama 不可达
- **THEN** 仍 MUST 能 `import` `OllamaLLMPlugin` 类并读取其 `name` / `interfaces`（仅在实际调用时才需 client/服务）

#### Scenario: 本地无凭证默认构造 client

- **WHEN** `OllamaLLMPlugin.initialize(context)` 执行且 `httpx` 可用
- **THEN** 因本地无需鉴权，插件 MUST 默认构造 HTTP 客户端，无需用户提供凭证；仅当 `api_key` 非占位值时才附带 `Authorization: Bearer` 头（支持带鉴权的远程代理）

#### Scenario: 默认后端保持 DeepSeek

- **WHEN** 加载 `MCSConfig.knowledge_graph()` 默认配置
- **THEN** 默认 LLM 插件 MUST 仍是 `deepseek_llm`；`ollama_llm` MUST 仅作为可选后端存在于注册表/工厂中

#### Scenario: 工厂与注册表可按名引用

- **WHEN** 用户 `MCSConfig.knowledge_graph(llm="ollama")` 或在 `plugins` 列表中以 `"ollama_llm"` 替换 `"deepseek_llm"`
- **THEN** 框架 MUST 能据名实例化 `OllamaLLMPlugin` 并解析为 `LLMInterface` 后端

---

### Requirement: 与 ContextRenderer 接线

On `initialize`, `OllamaLLMPlugin` MUST attach the framework-provided `ContextRenderer` (via `attach_renderer`) so the base `call` serializes nodes. The plugin MUST NOT serialize `Node` objects itself.

#### Scenario: 附加框架渲染器

- **WHEN** `OllamaLLMPlugin.initialize(context)` 执行
- **THEN** 它 MUST 调用 `attach_renderer(context.context_renderer)`

#### Scenario: 插件不见 raw Node

- **WHEN** `_raw_call` 被基类编排调用
- **THEN** 它 MUST 只接收已渲染好的 `system` / `user` 字符串；MUST NOT 直接访问 `node.extensions` 等字段

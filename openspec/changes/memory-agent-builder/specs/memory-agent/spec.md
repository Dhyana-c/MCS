## MODIFIED Requirements

### Requirement: 记忆工具集（learn / search / associate / reason / recall）

`MemoryAgent` SHALL 经 `ToolSpec` 注册表（`BUILTIN_TOOLS`）向 LLM 暴露**可配置的**导航工具集，**默认 5 个**（learn / search / associate / reason / recall），分发到 `MemoryStore` 对应原语；工具集经 `ToolsetConfig` 可启用/禁用子集、覆盖参数：

- `learn(text)` → `memory.learn`
- `search(query, mode)` → `memory.search`
- `associate(seed_id, mode)` → `memory.associate`
- `reason(source_id, target_id)` → `memory.find_path`
- `recall(limit)` → `memory.recall`

导航决策权交给 LLM：由 LLM 决定选哪个工具、哪个种子、哪种模式、哪两个节点。

#### Scenario: 默认暴露全部 5 工具

- **WHEN** 构造 agent 时未指定 `ToolsetConfig`（或缺省）
- **THEN** 暴露给 LLM 的工具 schemas MUST 为全部 5 个内置工具（learn / search / associate / reason / recall）

#### Scenario: 分发到 MemoryStore 原语

- **WHEN** LLM 调用任一已启用工具
- **THEN** MUST 经 dispatch 转发到对应 `MemoryStore` 原语（learn / search / associate / find_path / recall）

#### Scenario: 禁用工具不暴露给 LLM

- **WHEN** `ToolsetConfig.enabled` 排除某工具（如禁用未实现的 `recall`）
- **THEN** 该工具 MUST NOT 出现在传给 LLM 的 schemas 中
- **AND** LLM 调用该工具名 MUST 返回 `[error] 未知工具：{name}`

#### Scenario: 参数覆盖

- **WHEN** `ToolsetConfig.params` 为某工具指定参数（如 `{"find_path": {"max_hops": 8}}`）
- **THEN** dispatch 执行该工具时 MUST 应用覆盖后的参数（而非内置默认值）

#### Scenario: 未知工具

- **WHEN** LLM 调用不在已启用工具表中的工具名
- **THEN** MUST 返回 `[error] 未知工具：{name}`

---

### Requirement: LLM 调用可注入

`MemoryAgent` SHALL 接受 `AgentLLMInterface`（`chat(messages, tools) -> AssistantMessage`）可注入后端，而非绑定具体 LLM SDK；裸 callable（`llm_call(messages, tools) -> assistant_dict`）经 `CallableAgentLLM` 适配器自动包装，保持既有注入式测试兼容。

#### Scenario: 测试注入裸 callable mock

- **WHEN** 测试构造 `MemoryAgent(memory, scripted_llm_call)`，其中 `scripted_llm_call` 为裸 callable
- **THEN** loop MUST 经 `CallableAgentLLM` 适配使用该 callable，不依赖真实 LLM API

#### Scenario: 注入 AgentLLMInterface 后端

- **WHEN** 注入 `AgentLLMInterface` 子类实例
- **THEN** loop MUST 直接调用其 `chat()`，并把返回的 `AssistantMessage.trace` 计入追踪（替代读取 `assistant_dict["_trace"]`）

## ADDED Requirements

### Requirement: AgentConfig / AgentBuilder / create_agent 构造体系

`mcs_agent` SHALL 提供编程式与 YAML 双路径构造记忆 agent：`AgentConfig` 数据对象、`AgentBuilder(config).build() -> MemoryAgent`、`create_agent(...)` 工厂、`AgentConfig.from_file(path) -> AgentConfig`。`build()` 返回 `MemoryAgent`（**不**返回 FastAPI app；`create_app(agent)` 仍是独立一层）。**统一 LLM**：单一 `LLMConfig`（provider/model/api_key/base_url）同时驱动 agent 的 chat LLM 与 MCS 的 write/read LLM（provider 键映射两侧）；`mcs_config`（完整 MCSConfig）作逃逸口优先（想给 MCS 配不同 LLM 时）。

#### Scenario: 工厂编程式构建可用 agent

- **WHEN** 调用 `create_agent(db_path=..., llm_provider="deepseek", llm_api_key=..., llm_model=...)`（单一 LLM 配置）
- **THEN** MUST 返回可调 `chat()` 且 `learn`/`associate` 可用的 `MemoryAgent`（agent 与 MCS 共用此 LLM），无需 YAML、无需环境变量

#### Scenario: YAML 构造

- **WHEN** `AgentConfig.from_file("agent.yaml")` 后经 `AgentBuilder(config).build()`
- **THEN** MUST 返回按 YAML 配置构建的 `MemoryAgent`（YAML 承载统一 `llm` 配置）

#### Scenario: builder 产物为 agent 而非 app

- **WHEN** 调用 `AgentBuilder(config).build()`
- **THEN** 返回值 MUST 为 `MemoryAgent` 实例，MUST NOT 为 FastAPI app

#### Scenario: db_path 指向已有图谱

- **WHEN** `create_agent(db_path="existing.db", llm_provider=..., llm_api_key=..., ...)` 指向一个已有数据的 SQLite 图
- **THEN** 构建的 agent 的 `MemoryStore` MUST 加载该 db 的已有图数据（经 `Phase1Builder` + `SQLiteStore`，不重建空图）

#### Scenario: 缺图谱来源早失败

- **WHEN** `AgentConfig` 既无 `mcs_config` 也无 `db_path`
- **THEN** `build()` MUST 抛清晰错误（非静默空图）

#### Scenario: 缺 LLM 早失败

- **WHEN** `AgentConfig` 既无 `llm` 也无 `mcs_config`
- **THEN** `build()` MUST 抛清晰错误（提示无 LLM、`learn`/`associate` 不可用），MUST NOT 静默产出调用即崩的 agent

#### Scenario: mcs_config 逃逸口

- **WHEN** 同时给 `llm`（agent 用）与 `mcs_config`（MCS 用，含不同 LLM）
- **THEN** agent chat LLM MUST 取自 `llm`，MCS write/read LLM MUST 取自 `mcs_config`

---

### Requirement: AgentLLMInterface 可插拔 LLM 后端

`mcs_agent` SHALL 提供 `AgentLLMInterface` ABC（`chat(messages, tools) -> AssistantMessage`）+ **provider 键**注册表 `AGENT_LLM_REGISTRY`，按 `LLMConfig.provider` 选择后端；同一 provider 键同时映射 MCS 插件（`PROVIDER_TO_MCS_LLM`），实现统一 LLM 配置。`AssistantMessage` 含 `content` / `tool_calls` / `trace`（一等 trace，替代 dict `_trace` 键 hack）。内置 `OpenAIAgentLLM`（openai 兼容，覆盖 deepseek / ollama）与 `AnthropicAgentLLM`（原生 claude）。内部消息 / 工具格式以 openai chat-completions 为 lingua franca。

#### Scenario: 选 deepseek / ollama（openai 兼容）

- **WHEN** `llm.provider="deepseek"` 或 `"ollama"`
- **THEN** MUST 用 `OpenAIAgentLLM`（按 provider 默认 base_url），`chat()` 返回含 `content` / `tool_calls` / `trace` 的 `AssistantMessage`
- **AND** 同一 provider MUST 经 `PROVIDER_TO_MCS_LLM` 映射到对应 MCS 插件（deepseek / ollama）

#### Scenario: 选 claude（anthropic 原生）

- **WHEN** `llm.provider="claude"`
- **THEN** MUST 用 `AnthropicAgentLLM`（原生 claude）
- **AND** 未安装 `anthropic` 依赖时 MUST 抛清晰错误（不影响 openai-compat 后端可用性）

#### Scenario: trace 为一等字段

- **WHEN** 任一后端 `chat()` 返回
- **THEN** `AssistantMessage.trace` MUST 含 token 用量 / 延迟 / 工具名（`LLMCallTrace`），MUST NOT 依赖 dict `_trace` 键

#### Scenario: 未知 provider 早失败

- **WHEN** `llm.provider` 不在 `AGENT_LLM_REGISTRY`
- **THEN** 构建时 MUST 抛清晰错误，不静默回退

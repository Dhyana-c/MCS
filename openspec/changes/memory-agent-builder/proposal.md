## Why

`mcs_agent` 目前只有 `build_agent_from_env()` 一条**绑死环境变量**的构造路径：没有 config 对象 / builder / 工厂，无法编程式组装（测试、嵌入别的应用、前端配置都只能靠 env）；LLM 后端只有 openai 一种（`make_openai_llm_call`），换 claude / 别的客户端无路可走；`MEMORY_TOOLS` 与 `_dispatch` 硬编码，工具不能配置；指向已有图谱无干净 API（必须手写 yaml）。这阻碍它作为**可配置、可扩展的通用记忆引擎 agent** 被复用。LLM 的 `llm_call` callable 抽象已存在（可注入，很好），但缺后端注册表与一等 trace。

## What Changes

- **构造层**：引入 `AgentConfig` + `AgentBuilder(config).build() -> MemoryAgent` + `create_agent(...)` 工厂 + `AgentConfig.from_file(yaml)`。编程式（kwargs）与 YAML 双路径；builder 出 agent（`create_app(agent)` 仍独立）。
- **可插拔 LLM（路线 A2）**：`AgentLLMInterface` ABC（`chat(messages, tools) -> AssistantMessage(content, tool_calls, trace)`）+ 后端注册表 `AGENT_LLM_REGISTRY`。内置 `OpenAIAgentLLM`（覆盖 deepseek / openai / ollama-compat）与 `AnthropicAgentLLM`（原生 claude，msg 双向翻译）。trace 提为一等返回字段，替掉 openai 实现里偷偷塞 `_trace` dict 键的 hack。
- **工具配置（窄档）**：`ToolSpec(name, schema, handler)` 注册表 + `BUILTIN_TOOLS`（5 个内置）+ `ToolsetConfig(enabled?, params)`；builder 产 `(schemas_for_llm, dispatch_table)`；删掉 `loop.py` 里 `MEMORY_TOOLS` 硬编码 list 与 `_dispatch` 的 if/elif。**不做**自定义工具注册（registry 形状为将来留口）。
- **指定已有图谱**：`db_path` 提为一等旋钮（对齐 `create_mcs(db_path=)`）；加载已有数据由 `SQLiteStore` build 时自动完成（白送）。
- **消息格式**：openai chat-completions 作内部 lingua franca——ABC 只标准化"返回值"，`MemoryAgent` 的消息历史不动；仅 `AnthropicAgentLLM` 内部做 native↔openai 双向翻译。
- **兼容**：`build_agent_from_env` 降级为"env → `AgentConfig` → builder"的薄预设（`python -m mcs_agent` 与现有 4-env 契约不破）；`CallableAgentLLM` 适配器包裸 callable，使现有注入 callable 的测试零改动。

## Capabilities

### New Capabilities

<!-- 无全新 capability——全部并入既有 `memory-agent`（构造 / LLM / 工具 / 图谱入口都是 agent 自身能力的扩展） -->

### Modified Capabilities

- `memory-agent`：
  - **ADDED**：`AgentConfig` / `AgentBuilder` / `create_agent` 构造体系；`AgentLLMInterface` + 后端注册表（可插拔 LLM）；`ToolSpec` 工具注册表（可配置工具集）；`db_path` 指向已有图谱的入口。
  - **MODIFIED**：「记忆工具集」从硬编码 5 工具 → registry 驱动的可配置工具集（默认 5）；「LLM 调用可注入」从裸 callable → `AgentLLMInterface`（callable 经适配器仍兼容）；「环境变量构建生产 agent」实现改走 builder（env 契约保留）。

## Impact

### 代码变更

- **新增**：`mcs_agent/builder.py`（`AgentConfig` / `AgentBuilder` / `create_agent` / `AgentConfig.from_file`）；LLM 抽象与后端（重构 `mcs_agent/llm.py` 为 `AgentLLMInterface` + `OpenAIAgentLLM`，新增 `AnthropicAgentLLM`，加 `AGENT_LLM_REGISTRY` + `CallableAgentLLM` 适配器）；`ToolSpec` 工具注册表（`mcs_agent/tools.py` 或并入 `loop.py`）。
- **改写**：`loop.py` 的 `MemoryAgent`——接 `AgentLLMInterface`（callable 自动适配）+ `(schemas, dispatch)`，删硬编码 `MEMORY_TOOLS` / `_dispatch`；`app.py` 的 `build_agent_from_env` 改走 builder；`__init__.py` 导出新 API。
- **不动**：`memory.py`（`MemoryStore` 单线程模型、原语签名）、`FastAPI create_app`、前端、MCS 核心库。

### API 变更

- 新增 public：`AgentConfig`、`AgentBuilder`、`create_agent`、`AgentLLMInterface`、`AGENT_LLM_REGISTRY`、`OpenAIAgentLLM`、`AnthropicAgentLLM`、`CallableAgentLLM`、`ToolSpec`、`BUILTIN_TOOLS`、`ToolsetConfig`。
- `MemoryAgent` 构造签名变更：LLM 入参 `Callable` → `AgentLLMInterface`（callable 自动适配，注入 callable 的调用方不破）；工具由模块常量 → 可选 `ToolsetConfig`（缺省 = 全部 5 内置）。**对直接构造 `MemoryAgent` 的代码为 BREAKING**，但经适配器 + 缺省工具集，既有测试与 `build_agent_from_env` 路径保持工作。
- `MEMORY_TOOLS` 保留为**已废弃别名**（指向内置 schema 列表），避免 import 断裂；后续 change 移除。

### 依赖

- **新增 optional `anthropic`**：`AnthropicAgentLLM` 用（同 MCS `claude` optional extra 的做法，惰性 import；不装则该后端不可用，不影响 openai 后端）。
- `openai`（既有，`OpenAIAgentLLM` 沿用）。
- 前置：无（独立于当前 2 个 in-progress change）。

### 风险

- **`MemoryAgent` 构造签名 BREAKING**：直接 `MemoryAgent(memory, callable)` 的调用方需感知签名变化。缓解：`CallableAgentLLM` 适配器 + 缺省全工具集，使注入 callable 的测试零改动；`build_agent_from_env` 内部切换。
- **trace 口径变化**：`_trace` dict 键 → `AssistantMessage.trace` 字段；凡直接读 `assistant["_trace"]` 的代码需改读字段。缓解：该读取仅 `loop.py` 内部一处，随重构一并迁移。
- **anthropic native 翻译**：openai↔anthropic 消息 / tool_call 格式转换有边界（多模态 content、并行 tool_calls 等）。缓解：首版只支持 text + tool_calls 的子集，多模态留 TODO（同当前 openai 实现的 NOTE）。
- **线程模型不变**：本次不引入并发；"未来全局并发控制"为另一个 change。

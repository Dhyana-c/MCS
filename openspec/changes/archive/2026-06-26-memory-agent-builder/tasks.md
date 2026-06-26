# Implementation Tasks

> 重构 `mcs_agent` 构造层。按 design.md Migration Plan 分阶段，每阶段测试保持绿（适配器桥接）。`memory.py` / `create_app` / 前端 / MCS 核心**不动**。

## 1. LLM 抽象（A2）

- [x] 1.1 新增 `AssistantMessage` dataclass（`content` / `tool_calls` / `trace: LLMCallTrace | None`），放 `mcs_agent/llm.py` 或新 `mcs_agent/llms/base.py`。
- [x] 1.2 定义 `AgentLLMInterface` ABC：`chat(messages, tools) -> AssistantMessage`。
- [x] 1.3 `OpenAIAgentLLM`：把现 `make_openai_llm_call` 逻辑搬进类，trace 走 `AssistantMessage.trace`（不再塞 dict `_trace` 键）。
- [x] 1.4 `CallableAgentLLM` 适配器：包裸 callable `llm_call(messages, tools) -> dict`，`chat()` 调它并把 `dict["_trace"]` 提到 `AssistantMessage.trace`。
- [x] 1.5 `AGENT_LLM_REGISTRY`（provider 键：`deepseek`/`ollama` → `OpenAIAgentLLM`）+ `PROVIDER_TO_MCS_LLM` 映射（claude 在阶段 5 加）。
- [x] 1.6 `loop.py`：`MemoryAgent` LLM 入参标注 `AgentLLMInterface`，传入 callable 自动包 `CallableAgentLLM`；trace 读取从 `assistant.pop("_trace")` 改为 `msg.trace`；把 `AssistantMessage` 重建为 openai assistant dict（`{role, content, tool_calls}`，`tool_calls` 保完整结构 id/type/function）后再 append 进 messages。
- [x] 1.7 既有 `MemoryAgent(memory, scripted_callable)` 测试跑通（验证适配器零改动兼容）。

## 2. 工具注册表（窄档）

- [x] 2.1 定义 `ToolSpec(name, schema, handler)` dataclass；`handler: (MemoryStore, args) -> str`。
- [x] 2.2 `BUILTIN_TOOLS`：把现 5 工具的 schema + handler 落成注册表（handler 调 `memory.learn/search/associate/find_path/recall`）。
- [x] 2.3 `ToolsetConfig(enabled=None, params={})` dataclass。
- [x] 2.4 `build_toolset(BUILTIN_TOOLS, config) -> (schemas_for_llm, dispatch_table)`：启用过滤；`dispatch_table[name] = (handler, params)`（`params = config.params.get(name, {})`），供包装层 `handler(memory, {**llm_args, **params})` 合并（params 覆盖同名入参）。
- [x] 2.5 `loop.py`：`MemoryAgent` 签名改为 `(memory, llm, *, tools: ToolsetConfig | None = None, system_prompt=…, max_turns=8, summary_budget=1000, on_trace=None)`（除 memory/llm 外 keyword-only，防位置参数静默破坏），内部 `build_toolset(BUILTIN_TOOLS, tools or ToolsetConfig())` → `(schemas, dispatch)`，`tools=None` 即全 5 工具；`_dispatch` **保留为包装层**（timing + try/except + `ToolCallTrace`），删硬编码 if/elif 改 `entry = self.dispatch.get(name)`（缺省 → `[error] 未知工具：{name}`），调 `handler(memory, {**llm_args, **params})`。
- [x] 2.6 `MEMORY_TOOLS` 降级为**已废弃别名**（= 全 5 内置 schemas），保留外部 import 不断裂；加 deprecation 注释。

## 3. 构造体系

- [x] 3.1 新增 `mcs_agent/builder.py`：`LLMConfig`（统一：provider/model/api_key/base_url/**auth_token**——auth_token 仅 claude 用，Bearer）/ `AgentConfig`（`llm` / `mcs_config` / `db_path` / `tools` / `max_turns` / `summary_budget` / `system_prompt` / `on_trace`）。
- [x] 3.2 `AgentBuilder.build() -> MemoryAgent`：**步骤0 前置校验两条独立判据**——(a) `config.llm is None` → 报错"agent chat 无 LLM 后端"（与 mcs_config 有无无关）；(b) `config.mcs_config is None and config.db_path is None` → 报错"无图谱来源"。再按 design resolve 顺序定 `build_fn`——mcs_config 优先 `lambda: Phase1Builder(mcs_config').build()`（**db_path 在 `build()` 之前**用 `dataclasses.replace` 重建 plugin_configs 覆盖 sqlite path，**不就地改、不 deepcopy**）→ 否则（llm 已校验非 None）统一 `llm` 走 `lambda: create_mcs(llm=PROVIDER_TO_MCS_LLM[llm.provider], db_path=db_path, plugin_configs={f"{PROVIDER_TO_MCS_LLM[llm.provider]}_llm": {model, api_key, base_url[, auth_token if claude]}})`（**⚠️ plugin_configs key = 完整插件名，走同一 `PROVIDER_TO_MCS_LLM` 短名映射（如 `deepseek_llm`），非 provider 键**——错则建死 key、MCS 侧 LLM 保持默认空 key 静默失败；**复用 `create_mcs`，不重写组装**）。`llm_backend` 直接 `AGENT_LLM_REGISTRY[llm.provider](...)`（**callable→CallableAgentLLM 适配不在 builder，在 `MemoryAgent.__init__`**）。
- [x] 3.3 `db_path` resolve：验证加载已有 db 数据（`SQLiteStore` 自动加载）；验证**两条独立报错判据**——缺 `llm`（含"只给 mcs_config 不给 llm"）报错、无 `mcs_config` 且无 `db_path` 报错；验证 `mcs_config` 逃逸口（agent 取 `llm`、MCS 取 `mcs_config`）。
- [x] 3.4 `create_agent(*, db_path=, llm_provider=, llm_api_key=, llm_model=, llm_base_url=, llm_auth_token=None, mcs_config=None, **kw) -> MemoryAgent` 工厂。
- [x] 3.5 `AgentConfig.from_file(path) -> AgentConfig`（YAML，承载统一 `llm`——含可选 `auth_token` 键——+ 可选 `mcs_config`：**指向独立 mcs.yaml 的路径**，惰性调 `MCSConfig.from_file` 解析（复用其 preset/overlay/env_expand，不在 agent.yaml 重实现 MCSConfig 解析）；惰性 import PyYAML）。

## 4. env 预设（兼容）

- [x] 4.1 `app.py` 的 `build_agent_from_env()` 改走 builder：读 `MCS_CONFIG` / `AGENT_LLM_API_KEY` / `AGENT_LLM_MODEL` / `AGENT_LLM_BASE_URL` → 构 `AgentConfig` → `AgentBuilder(config).build()`。
- [x] 4.2 验证 env 契约与早失败行为逐字保留（缺 `MCS_CONFIG` / `AGENT_LLM_API_KEY` 仍 `SystemExit` 非零）。
- [x] 4.3 `python -m mcs_agent` 启动路径回归通过。

## 5. anthropic 后端

- [x] 5.1 `AnthropicAgentLLM`：原生 claude，构造接 `auth_token`/`api_key`（auth_token 优先，对齐 claude_llm）；`chat()` 内做 openai↔anthropic 消息 / tool_call 双向翻译（每轮整段 history）；首版仅 text + tool_calls 子集（多模态留 TODO）。**翻译测试边界**（mock SDK）：连续多轮 tool_call 的 tool_use/tool_result id 配对回放、`content=None` 的 assistant 消息、混 tool_result 的多轮历史、system 段映射。
- [x] 5.2 注册进 `AGENT_LLM_REGISTRY["claude"]` + `PROVIDER_TO_MCS_LLM["claude"]`；未装 `anthropic` 时清晰报错。
- [x] 5.3 `pyproject.toml` 加 optional extra `agent-anthropic`（或复用 `claude` extra），惰性 import。

## 6. 收尾

- [x] 6.1 `__init__.py` 导出新 public API（`LLMConfig` / `AgentConfig` / `AgentBuilder` / `create_agent` / `AgentLLMInterface` / `AGENT_LLM_REGISTRY` / `OpenAIAgentLLM` / `AnthropicAgentLLM` / `CallableAgentLLM` / `ToolSpec` / `BUILTIN_TOOLS` / `ToolsetConfig` / `AssistantMessage`）；**保留** `make_openai_llm_call` 导出（废弃别名，见 design D8）。
- [x] 6.2 补 / 迁移测试：builder 各路径（kwargs / yaml / db_path 加载已有图 / **缺 llm 报错（两条独立用例：(a) 无 llm 无 mcs_config；(b) 只给 mcs_config 不给 llm——必须也报错，因 mcs_config 的 LLM 无 tool-calling 救不了 agent chat）** / 缺图谱来源报错（无 mcs_config 且无 db_path） / **统一 llm 喂 agent+MCS（必须断言 MCS 侧 `deepseek_llm`/`claude_llm`/`ollama_llm` 插件 config 实际收到 api_key/model/base_url/auth_token，而非仅断言构建不报错——否则 plugin key 错配会静默漏过）** / **mcs_config 逃逸口（+ db_path 覆盖其 sqlite path 生效、不污染原 MCSConfig 对象）**）、工具启用禁用 + 参数覆盖（params 覆盖同名入参）、provider 选择 + 未知 provider 报错（含 openai）、**claude auth_token 同源种入 agent + MCS**、callable 适配兼容（在 `MemoryAgent.__init__` 层，不经 builder）、anthropic 翻译（mock SDK）。
- [x] 6.3 更新 `docs/memory-agent.md`：构造方式（create_agent / yaml / env）、可插拔 LLM 后端表（统一 provider 集 {deepseek, ollama, claude}、claude `auth_token`、openai 不可作统一键）、工具配置说明、db_path 指向已有图谱。
- [x] 6.4 全量测试 `.venv\Scripts\python.exe -m pytest -q` 通过。

## 7. 校验

- [x] 7.1 `openspec validate memory-agent-builder` 通过。
- [x] 7.2 核对 spec delta：MODIFIED「记忆工具集」「LLM 调用可注入」+ ADDED 2 条，场景为 4 井号、可测。
- [x] 7.3 确认 `memory.py` / `create_app` / 前端 / `mcs/` 核心零改动（diff 只在 `mcs_agent/` + docs + pyproject）。

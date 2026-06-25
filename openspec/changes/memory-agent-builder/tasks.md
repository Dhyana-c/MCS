# Implementation Tasks

> 重构 `mcs_agent` 构造层。按 design.md Migration Plan 分阶段，每阶段测试保持绿（适配器桥接）。`memory.py` / `create_app` / 前端 / MCS 核心**不动**。

## 1. LLM 抽象（A2）

- [ ] 1.1 新增 `AssistantMessage` dataclass（`content` / `tool_calls` / `trace: LLMCallTrace | None`），放 `mcs_agent/llm.py` 或新 `mcs_agent/llms/base.py`。
- [ ] 1.2 定义 `AgentLLMInterface` ABC：`chat(messages, tools) -> AssistantMessage`。
- [ ] 1.3 `OpenAIAgentLLM`：把现 `make_openai_llm_call` 逻辑搬进类，trace 走 `AssistantMessage.trace`（不再塞 dict `_trace` 键）。
- [ ] 1.4 `CallableAgentLLM` 适配器：包裸 callable `llm_call(messages, tools) -> dict`，`chat()` 调它并把 `dict["_trace"]` 提到 `AssistantMessage.trace`。
- [ ] 1.5 `AGENT_LLM_REGISTRY`（provider 键：`deepseek`/`ollama` → `OpenAIAgentLLM`）+ `PROVIDER_TO_MCS_LLM` 映射（claude 在阶段 5 加）。
- [ ] 1.6 `loop.py`：`MemoryAgent` LLM 入参标注 `AgentLLMInterface`，传入 callable 自动包 `CallableAgentLLM`；trace 读取从 `assistant.pop("_trace")` 改为 `assistant.trace`。
- [ ] 1.7 既有 `MemoryAgent(memory, scripted_callable)` 测试跑通（验证适配器零改动兼容）。

## 2. 工具注册表（窄档）

- [ ] 2.1 定义 `ToolSpec(name, schema, handler)` dataclass；`handler: (MemoryStore, args) -> str`。
- [ ] 2.2 `BUILTIN_TOOLS`：把现 5 工具的 schema + handler 落成注册表（handler 调 `memory.learn/search/associate/find_path/recall`）。
- [ ] 2.3 `ToolsetConfig(enabled=None, params={})` dataclass。
- [ ] 2.4 `build_toolset(BUILTIN_TOOLS, config) -> (schemas_for_llm, dispatch_table)`：启用过滤 + params 覆盖应用。
- [ ] 2.5 `loop.py`：`MemoryAgent` 接 `(schemas, dispatch)`；`_dispatch` **保留为包装层**（timing + try/except + `ToolCallTrace`），删硬编码 if/elif 改 `handler = self.dispatch.get(name)`（缺省 → `[error] 未知工具：{name}`），调 `handler(memory, args)`。
- [ ] 2.6 `MEMORY_TOOLS` 降级为**已废弃别名**（= 全 5 内置 schemas），保留外部 import 不断裂；加 deprecation 注释。

## 3. 构造体系

- [ ] 3.1 新增 `mcs_agent/builder.py`：`LLMConfig`（统一：provider/model/api_key/base_url）/ `AgentConfig`（`llm` / `mcs_config` / `db_path` / `tools` / `max_turns` / `summary_budget` / `system_prompt` / `on_trace`）。
- [ ] 3.2 `AgentBuilder.build() -> MemoryAgent`：按 design resolve 顺序——mcs_config 优先（db_path 覆盖其 sqlite path）→ 否则用统一 `llm` 构 MCSConfig（write_llm=read_llm=`PROVIDER_TO_MCS_LLM[llm.provider]` + 种插件凭证 + sqlite path）→ 缺 `llm` 且无 `mcs_config` 报错。
- [ ] 3.3 `db_path` resolve：验证加载已有 db 数据（`SQLiteStore` 自动加载）；验证缺 `llm` 且无 `mcs_config` 时清晰报错；验证 `mcs_config` 逃逸口（agent 取 `llm`、MCS 取 `mcs_config`）。
- [ ] 3.4 `create_agent(*, db_path=, llm_provider=, llm_api_key=, llm_model=, llm_base_url=, mcs_config=None, **kw) -> MemoryAgent` 工厂。
- [ ] 3.5 `AgentConfig.from_file(path) -> AgentConfig`（YAML，承载统一 `llm` + mcs_config；惰性 import PyYAML）。

## 4. env 预设（兼容）

- [ ] 4.1 `app.py` 的 `build_agent_from_env()` 改走 builder：读 `MCS_CONFIG` / `AGENT_LLM_API_KEY` / `AGENT_LLM_MODEL` / `AGENT_LLM_BASE_URL` → 构 `AgentConfig` → `AgentBuilder(config).build()`。
- [ ] 4.2 验证 env 契约与早失败行为逐字保留（缺 `MCS_CONFIG` / `AGENT_LLM_API_KEY` 仍 `SystemExit` 非零）。
- [ ] 4.3 `python -m mcs_agent` 启动路径回归通过。

## 5. anthropic 后端

- [ ] 5.1 `AnthropicAgentLLM`：原生 claude，`chat()` 内做 openai↔anthropic 消息 / tool_call 双向翻译；首版仅 text + tool_calls 子集（多模态留 TODO）。
- [ ] 5.2 注册进 `AGENT_LLM_REGISTRY["claude"]` + `PROVIDER_TO_MCS_LLM["claude"]`；未装 `anthropic` 时清晰报错。
- [ ] 5.3 `pyproject.toml` 加 optional extra `agent-anthropic`（或复用 `claude` extra），惰性 import。

## 6. 收尾

- [ ] 6.1 `__init__.py` 导出新 public API（`AgentConfig` / `AgentBuilder` / `create_agent` / `AgentLLMInterface` / `AGENT_LLM_REGISTRY` / `OpenAIAgentLLM` / `AnthropicAgentLLM` / `CallableAgentLLM` / `ToolSpec` / `BUILTIN_TOOLS` / `ToolsetConfig` / `AssistantMessage`）。
- [ ] 6.2 补 / 迁移测试：builder 各路径（kwargs / yaml / db_path 加载已有图 / 缺来源报错 / **缺 llm 且无 mcs_config 报错** / **统一 llm 喂 agent+MCS** / **mcs_config 逃逸口**）、工具启用禁用 + 参数覆盖、provider 选择 + 未知 provider 报错、callable 适配兼容、anthropic 翻译（mock SDK）。
- [ ] 6.3 更新 `docs/memory-agent.md`：构造方式（create_agent / yaml / env）、可插拔 LLM 后端表、工具配置说明、db_path 指向已有图谱。
- [ ] 6.4 全量测试 `.venv\Scripts\python.exe -m pytest -q` 通过。

## 7. 校验

- [ ] 7.1 `openspec validate memory-agent-builder` 通过。
- [ ] 7.2 核对 spec delta：MODIFIED「记忆工具集」「LLM 调用可注入」+ ADDED 2 条，场景为 4 井号、可测。
- [ ] 7.3 确认 `memory.py` / `create_app` / 前端 / `mcs/` 核心零改动（diff 只在 `mcs_agent/` + docs + pyproject）。

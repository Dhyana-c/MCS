## Why

`mcs_mcp` 现状是 MCS 框架的**薄 MCP 适配**：`query`→`mcs.query`+`render_query_result`、`ingest`→`mcs.ingest`+`format_ingest_status`，暴露的是单次粗粒度框架查询。但项目的查询驱动已**全面转向 agent**——`mcs_agent` 的 ReAct loop（12 工具 + 会话上下文预算自治）经 multihop bench 证明优于框架 BFS（见 archived `framework-to-agent-handoff` 决策），`mcs_mem` 应用层也已走 agent。MCP 作为对外入口却仍停留在框架直查，能力与 agent 脱节。

本 change 把 `mcs_mcp` 后端从 MCS 框架管线**全部切到 `mcs_agent`**：`query` 走 `agent.chat` 多步探索、`ingest` 走 `agent.memory.learn`，让 MCP 入口对齐 agent 能力。`mcs_mcp` 当前无人使用，可放手重写、无需向后兼容。

## What Changes

- **`mcs_mcp/server.py` 主体重写**：`MCPServer` 持有 `MemoryAgent`（经 `create_agent` 构造）而非 `MCS` 实例；`query`→`agent.chat`、`ingest`→`agent.memory.learn`；**删自建单 worker executor**——串行 + SQLite 线程亲和收敛到 `MemoryStore` 自带的单 worker（`memory.py`，`max_workers=1`），外层仅 `asyncio.to_thread` 桥防阻塞 stdio 事件循环。
- **LLM 复用 MCS yaml**：从 `MCSConfig.plugin_configs` 反推 `LLMConfig`（识别 `{deepseek,ollama,claude}_llm` 键），**不新增配置文件、不要求 `AGENT_LLM_*` env**。无识别键 / 多 LLM 歧义 / provider 不在 agent 支持集 → 启动期清晰早失败并以非零码退出。
- **shutdown 路径**：进程退出（含异常路径）MUST 调 `agent.memory.shutdown()`（worker 线程内关 MCS + `executor.shutdown`），`main` 同步 finally 调；注册 `SIGTERM`→`KeyboardInterrupt`（POSIX）保证 finally 在强制退出下可达。
- **BREAKING — `query` 返回值语义变更**：从 `render_query_result` 的结构化节点/边渲染文本 → agent ReAct 多步探索后的**自然语言答复**（含 `[id:...]` 存根引用）。`ingest` 返回格式不变（`format_ingest_status` 渲染纯函数下沉到 `MemoryStore.learn` 委托，文本逐字一致）。
- **顺手修核心 bug（3 处资源泄漏）**：① `AgentBuilder.build` 步骤 3/4 失败兜底 `memory.shutdown()`；② `MemoryStore.__init__` 的 `_submit(build_fn)` 失败兜底 `executor.shutdown`（坏 yaml / 坏 sqlite path——构造失败最高频路径）；③ `OpenAIAgentLLM` / `AnthropicAgentLLM._get_client` 加 `threading.Lock` 防 double-init（治本、惠及所有调用方）。三处均零行为变化，核心代码必须绝对正确。
- **import 切换 + 依赖边界**：`mcs_mcp` 不再 import `mcs.query` / `mcs.ingest` / `mcs.presets` / `mcs.rendering`，改 import `mcs_agent.{builder,loop,llms}`；**严禁** import `mcs_agent.app`（会拉 fastapi/pydantic/uvicorn，mcp stdio 不需要）。`mcs_mcp → mcs_agent` 是公开 API 边界；`mcs_agent` 内部调 `mcs.core`（如 `memory.learn`→`mcs.ingest`）是实现细节、非 `mcs_mcp` 直接依赖。
- **测试**：`test_mcp_server.py` 重写——`MCPServer.from_agent` 类方法注入 `FakeMemoryAgent` 测透传 / 异常隔离 / 早失败（A 类：mcs_mcp 层单测，agent 是 collaborator）；`CallableAgentLLM` + 真实 `MemoryStore` + `FakeMCS` 测 ReAct loop 的 max_turns 兜底 / 降级 / 异常隔离（B 类：走真实 loop，符合不 mock 铁律）；新增构造期早失败测试（无 `_llm` / 多 `_llm` / provider 不支持）。
- **docs**：`docs/mcp-server.md` / `README.md` 同步——query 语义、LLM 复用配置说明、串行由 `MemoryStore` 单 worker 保证、max_turns 与 MCP 客户端超时提示。
- **spec**：修订 `mcp-server` capability（**5 条改写 + 4 条新增 + 1 条移除**），逐 Scenario before→after 对照。

## Capabilities

### New Capabilities

（无——本 change 是工程 / 接入层重写，**不改核心图模型**：4 类节点 / 边模型 / 不变量 / 守门 / 双层 / universe 归属轴均零改动。）

### Modified Capabilities

- `mcp-server`：后端从 MCS 框架改为 `mcs_agent`（`query`→`agent.chat`、`ingest`→`memory.learn`）；LLM 复用 MCS yaml 反推 + 早失败；shutdown 路径调 `agent.memory.shutdown`；线程模型收敛到 `MemoryStore` 单 worker。**改写 5 条** requirement（构建启动 / ingest 摘要 / 串行化与线程亲和 / 可选依赖与入口 / 单次工具异常隔离）、**新增 4 条**（后端为 mcs_agent / query 委托 agent 多步探索 / LLM 复用反推 / shutdown 路径）、**移除 1 条**（query 结果渲染为 LLM 可读文本——后端切 agent 后渲染委托不再适用）；「暴露 query 与 ingest 工具」requirement agent 化后零语义变更、原样保留。

## Impact

- **代码**：`mcs_mcp/server.py`（主体重写，含新增 `_llm_config_from_mcs` 反推函数、`MCPServer.from_agent` 测试注入类方法）；`mcs_agent/builder.py` + `mcs_agent/memory.py`（两处构造期失败兜底，清理 `MemoryStore`/executor——核心 bug 修复）；`mcs_agent/llms/{openai,anthropic}.py`（`_get_client` 加锁防 double-init）；`tests/test_mcp_server.py`（重写）。
- **配置**：**零新增**——仍只读一个 MCS yaml（`MCS_CONFIG` / `--config`）；YAML 的 `plugin_configs` MUST 含 `{deepseek|ollama|claude}_llm` 之一段（否则 mcs_mcp 启动早失败并提示）。
- **接口契约**：`mcs_mcp` 重写后依赖 `mcs_agent` 的 `create_agent` / `MemoryAgent.chat` / `MemoryAgent.memory` / `MemoryStore.{learn,shutdown}` / `AGENT_LLM_REGISTRY`——同 `mcs-core` 发行物内部依赖、非跨仓（`mcs-mem-extract-and-publish` 的跨包稳定契约清单不涉及，mcs_mcp 与 mcs_agent 同发行物）。
- **破坏性**：`query` 工具返回值从结构化渲染文本 → agent 自然语言答复（migration note 供未来追溯；当前无人用）。
- **依赖**：`mcs_mcp` 依赖 `mcs_agent`（随 `mcs-core` 发行）；MUST NOT 间接依赖 fastapi（严禁 import `mcs_agent.app`）；`mcp` / `PyYAML` 仍为可选 `[mcp]` extra。
- **文档**：`docs/mcp-server.md`、`README.md` 同步。
- **不变量**：核心图模型、守门、活跃视图不变量零改动。

## Why

MCS 已具备知识图谱的写入（`ingest`）与查询（`query`）能力，但缺少一个**面向用户的对话入口**——让用户用自然语言与记忆图谱交互：查询相关记忆、让 agent 记住新信息。

需要一个**记忆 agent 应用骨架**，复用 MCS 现状底座（事实作为边）跑通端到端对话，验证应用层可行性。算法层（置信度动态计算、Hub 折叠、事件节点）在命门验证前不引入（详见 `docs/memory-agent-design.md`），故本提案只覆盖应用骨架。

## What Changes

### 应用层（新增 `mcs/agent/`）

- **MemoryStore**：MCS 的单 worker 线程包装。MCS 非线程安全、SQLite 连接绑创建线程，故 MCS 构造与全部调用都序列化到同一 worker 线程（同 mcp-server 模式）。复用 mcp-server 的渲染纯函数，不重复实现。
- **MemoryAgent**：ReAct loop。agent 自有 LLM（独立于 MCS 的 read_llm），经 openai 兼容 tool calling 调记忆工具。LLM 调用抽成可注入 callable，便于测试注入 mock。
- **工具**（本提案版本）：`memory_query`（查记忆）、`memory_ingest`（写记忆）两个粗粒度工具。细粒度导航工具体系由后续 `memory-agent-navigation` 提案演进。
- **FastAPI 后端**：`/chat`（POST，`message`→`reply`）、`/health`，CORS，静态前端挂载。`create_app(agent)` 接受任意带 `chat()` 的对象，可注入 fake。
- **前端**：纯 HTML+CSS+JS 聊天页，fetch `/chat`。
- **启动入口**：`python -m mcs.agent`，从环境变量构建生产 agent 并起 uvicorn。

## Capabilities

### New Capabilities

- `memory-agent`：基于 MCS 的记忆 agent 应用骨架（单线程 MCS 包装 + ReAct loop + FastAPI + 前端 + 启动入口）

### Modified Capabilities

- `mcp-server`：无 spec 级变更；agent 复用其 query/ingest 渲染纯函数

## Impact

### 代码变更

| 文件 | 变更类型 | 说明 |
|------|----------|------|
| `mcs/agent/__init__.py` | 新增 | 导出 MemoryAgent / MemoryStore / make_openai_llm_call / 工具常量 |
| `mcs/agent/memory.py` | 新增 | MemoryStore：单 worker 线程包 MCS，复用 mcp-server 渲染纯函数 |
| `mcs/agent/loop.py` | 新增 | MemoryAgent ReAct loop + DEFAULT_SYSTEM_PROMPT + 工具表 + _dispatch |
| `mcs/agent/llm.py` | 新增 | make_openai_llm_call 工厂（openai 兼容，openai 惰性 import） |
| `mcs/agent/app.py` | 新增 | create_app / build_agent_from_env / run |
| `mcs/agent/static/index.html` | 新增 | 聊天前端 |
| `mcs/agent/__main__.py` | 新增 | `python -m mcs.agent` 入口 |
| `tests/test_agent_loop.py` | 新增 | 10 测试（mock LLM + fake memory） |
| `tests/test_agent_app.py` | 新增 | 6 测试（FastAPI TestClient + fake agent） |
| `pyproject.toml` | 修改 | 加 `[agent]` optional 依赖（fastapi、uvicorn）；dev 加 httpx |

### 依赖关系

- 仅依赖 MCS 公共 API（`ingest`/`query`/`query_engine`/`read_manager`）与 mcp-server 渲染纯函数，不修改 MCS 核心。
- fastapi/uvicorn/openai 为 optional 依赖，不影响核心库默认安装。

### 风险

- **低风险**：纯新增应用层，MCS 核心不动；全量测试不受影响。
- **未接算法层**：记忆侧即 MCS 原生 query/ingest，无置信度/折叠/事件——已知限制，非缺陷。
- **CORS 全开**：仅开发期，生产需按域名收紧。

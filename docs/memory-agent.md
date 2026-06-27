# 记忆 Agent

> `mcs_agent` 是建在 MCS 之上的对话式记忆助手：一个 **ReAct loop**，让 LLM 经 tool calling 自主决定
> 如何在记忆图里导航。本文讲架构、5 个导航工具、单线程封装、FastAPI 后端、启动方式，以及它与 MCP server
> 的区别。代码在顶层 `mcs_agent/` 包。

## 架构

```
浏览器前端 (static/)  ──HTTP──▶  FastAPI (app.py)  ──▶  MemoryAgent (loop.py)
                                     │                      │ ReAct loop（自有 LLM）
                                     │                      ▼
                                     └──/graph/expand──▶  MemoryStore (memory.py)
                                                            │ 单 worker 线程
                                                            ▼
                                                           MCS（图 + 读写管线）
```

- **MemoryAgent**（`loop.py`）：ReAct 循环。每轮把最新**图级主题摘要**注入 system prompt（让"要不要进图
  探索"的路由判断有据），LLM 返回工具调用或最终答复；工具结果回灌、最多 `max_turns` 轮。
- **自有 LLM（可插拔）**：agent 的 chat LLM **独立于 MCS 的 `read_llm`**，实现 `AgentLLMInterface`
  （`chat(messages, tools) -> AssistantMessage`）。内置 `OpenAIAgentLLM`（openai 兼容，覆盖 deepseek / ollama）
  与 `AnthropicAgentLLM`（原生 claude）；裸 callable 经 `CallableAgentLLM` 自动适配（测试可注入脚本化 mock）。
  详见下文「构造与可插拔 LLM 后端」。
- **导航决策权在 LLM**：选哪个工具、哪个种子、哪种扩展模式、找哪两个节点的路径，都由 LLM 决定；工具只是对
  MCS 能力的薄封装。

## 5 个导航工具

`BUILTIN_TOOLS`（`tools.py`，`ToolSpec` 注册表）定义的工具，经 tool calling 暴露给 agent 的 LLM
（`MEMORY_TOOLS` 保留为废弃别名）。工具集可经 `ToolsetConfig` 配置（启用子集 / 按工具名覆盖参数）：

| 工具 | 参数 | 作用 | 状态 |
|------|------|------|------|
| `learn` | `text` | 把信息写入记忆图（复用 MCS 写管线，自动抽概念入图）。仅当用户明确要求记住时调用 | ✅ |
| `search` | `query`, `mode` | 搜入口种子。`keyword`=字面匹配名 / 别名（主力）；`direct`=顶层 hub；`vector`=向量检索 | keyword ✅ / direct ✅ / vector ✗ |
| `associate` | `seed_id`, `mode` | 从种子 BFS 联想扩展。`mcs`=事实 BFS（主力）；`hot`/`random` | mcs ✅ / hot·random ✗ |
| `reason` | `source_id`, `target_id` | 在两个已知节点间找连通路径（无向 BFS，允许失败） | ✅ |
| `recall` | `limit` | 回忆最近发生的事件（时间倒排、纯近期口径，受 `limit` 与 T 双约束） | ✅ |

未实现的模式以**空壳诚实返回**提示（不伪造）；工具返回的节点都带 `[id:...]`，供后续工具引用
（`search → associate → reason` 链式导航）。

## MemoryStore：MCS 的单线程封装

MCS 非线程安全、SQLite 连接绑创建线程，所以 `MemoryStore`（`memory.py`）把 MCS 的**构造与全部调用都收束到
同一个单 worker 线程**（`ThreadPoolExecutor(max_workers=1)`）：每个原语经 `_submit` 丢给 worker、阻塞取结果，
调用方线程绝不直接触碰 MCS / store。

它在 5 个 LLM 工具之外还暴露 `graph_summary`（读图级主题摘要）、`graph_view`（只读可视化视图）
等原语。其中 `find_path` 是 `reason` 工具背后的无向 BFS（下钻成员 + 关系边端点都算邻居）。

## FastAPI 后端

`app.py` 的 `create_app(agent)` 挂三个路由 + 静态前端兜底：

| 路由 | 方法 | 作用 |
|------|------|------|
| `/chat` | POST `{message}` → `{reply}` | 跑一轮 agent ReAct |
| `/health` | GET | 健康检查 `{ok: true}` |
| `/graph/expand` | GET `?node_id=__seed_root__` | 只读图谱可视化：转发 `memory.graph_view`（缺省虚拟根） |

`/` 兜底挂 `static/`（前端 `index.html`，对话 + Cytoscape 图谱可视化）。CORS 开发期全开、生产按域名收紧。

## 构造与可插拔 LLM 后端

`mcs_agent` 提供编程式 / YAML / 环境变量三条构造路径，都经 `AgentBuilder`：

```python
from mcs_agent import create_agent, AgentConfig, AgentBuilder

# 1. 工厂（kwargs）——一份 LLM 配置同时喂 agent chat 与 MCS 抽取
agent = create_agent(
    db_path="mem.db", llm_provider="deepseek",
    llm_model="deepseek-chat", llm_api_key="sk-...",
)

# 2. YAML（agent.yaml 承载统一 llm + 可选 mcs_config 路径 + db_path / tools）
cfg = AgentConfig.from_file("agent.yaml")
agent = AgentBuilder(cfg).build()
```

**统一 LLM**：单一 `LLMConfig`（provider/model/api_key/base_url/auth_token）同时驱动 agent 的 chat LLM
与 MCS 的 write/read LLM（provider 键映射两侧）。`mcs_config`（完整 MCSConfig）作逃逸口——想给 MCS 配不同
LLM 时传它（此时 agent chat LLM 仍取 `llm`）。

可插拔 LLM 后端（按 `LLMConfig.provider` 选；统一 provider 集 = agent adapter ∩ MCS 插件）：

| provider | agent adapter | MCS 插件 | 说明 |
|---|---|---|---|
| `deepseek` | `OpenAIAgentLLM` | `deepseek_llm` | openai 兼容；默认 base_url `https://api.deepseek.com` |
| `ollama` | `OpenAIAgentLLM` | `ollama_llm` | openai 兼容；默认 `http://localhost:11434/v1`；需任意占位 `api_key`（openai SDK 要求非空） |
| `claude` | `AnthropicAgentLLM` | `claude_llm` | anthropic 原生；`auth_token`（Bearer）优先于 `api_key` |

> 官方 `openai` 无 MCS 插件，**不作统一 provider 键**（落入"未知 provider 早失败"）。要连任意 openai 兼容
> 端点，用 `deepseek`/`ollama` 键 + 自定义 `base_url`；想给 MCS 配独立 LLM 走 `mcs_config` 逃逸口。

`db_path` 指向已有 SQLite 图时，`SQLiteStore` 构造时自动加载其数据（不重建空图）。

## 启动

```bash
export MCS_CONFIG=/path/to/mcs.yaml       # MCS 图配置（→ mcs_config 逃逸口，MCS LLM 由 yaml 决定）
export AGENT_LLM_API_KEY=sk-...           # agent chat LLM
export AGENT_LLM_MODEL=deepseek-chat
export AGENT_LLM_PROVIDER=deepseek        # 默认 deepseek；可选 ollama / claude
# export AGENT_LLM_BASE_URL=...           # 可选，自定义端点（覆盖 provider 默认）
python -m mcs_agent                        # 默认 http://127.0.0.1:8000
```

缺关键环境变量时以非零码退出（早失败）。也可不经 env，直接 `create_app(create_agent(...))` 编程式启动。

## 与 MCP Server 的区别

| | MCP Server（`mcs_mcp`） | 记忆 Agent（`mcs_agent`） |
|---|---|---|
| 谁来决策 | **外部客户端**（Claude Desktop 等）的 LLM | **自带** LLM（ReAct loop） |
| 接口 | MCP stdio 工具（`query` / `ingest`） | HTTP（`/chat`）+ 前端 |
| 工具粒度 | 粗（一次 query 走完整管线） | 细（5 个导航原语，LLM 分步组合） |
| 用途 | 把图当工具接入已有 Agent | 独立的对话式记忆助手 |

两者都用单 worker 线程封装 MCS（线程安全铁律），都复用 `mcs.rendering` 的渲染纯函数。

## 进一步阅读

- [architecture.md](architecture.md) — MCS 本体
- [getting-started.md](getting-started.md) §7 — 一行启动
- [mcp-server.md](mcp-server.md) — 另一种暴露方式

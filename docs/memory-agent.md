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
- **自有 LLM**：agent 的 LLM **独立于 MCS 的 `read_llm`**——`llm_call(messages, tools)` 抽成可注入 callable
  （遵循 openai chat completions 格式），测试可注入脚本化 mock，不依赖真实 API。
- **导航决策权在 LLM**：选哪个工具、哪个种子、哪种扩展模式、找哪两个节点的路径，都由 LLM 决定；工具只是对
  MCS 能力的薄封装。

## 5 个导航工具

`MEMORY_TOOLS`（`loop.py`）定义的工具，经 tool calling 暴露给 agent 的 LLM：

| 工具 | 参数 | 作用 | 状态 |
|------|------|------|------|
| `learn` | `text` | 把信息写入记忆图（复用 MCS 写管线，自动抽概念入图）。仅当用户明确要求记住时调用 | ✅ |
| `search` | `query`, `mode` | 搜入口种子。`keyword`=字面匹配名 / 别名（主力）；`direct`=顶层 hub；`vector`=向量检索 | keyword ✅ / direct ✅ / vector ✗ |
| `associate` | `seed_id`, `mode` | 从种子 BFS 联想扩展。`mcs`=事实 BFS（主力）；`hot`/`random` | mcs ✅ / hot·random ✗ |
| `reason` | `source_id`, `target_id` | 在两个已知节点间找连通路径（无向 BFS，允许失败） | ✅ |
| `recall` | `limit` | 回忆近期热点事件 | ✗（依赖事件热点排序） |

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

## 启动

```bash
export MCS_CONFIG=/path/to/mcs.yaml       # MCS 图配置（MemoryStore 经 Phase1Builder build）
export AGENT_LLM_API_KEY=sk-...           # agent 自有 LLM（openai 兼容端点）
export AGENT_LLM_MODEL=deepseek-chat
# export AGENT_LLM_BASE_URL=...           # 可选，自定义端点
python -m mcs_agent                        # 默认 http://127.0.0.1:8000
```

缺关键环境变量时以非零码退出（早失败）。

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

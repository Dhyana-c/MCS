# MCP Server

> 把 MCS 作为 **MCP（Model Context Protocol）server** 暴露，让 Claude Desktop 等客户端
> 把知识图谱当工具用：`query` 查询、`ingest` 摄入。传输用 **stdio**（本地标准）。
>
> 后端走 **mcs_agent**：`query` 经 agent ReAct 多步探索（search→associate→reason 等）返回
> 自然语言答复（含 `[id:...]` 节点引用，**不再渲染结构化节点/边**）；`ingest` 经 `agent.memory.learn` 写图。

## 安装

```bash
pip install -e ".[mcp]"   # 安装 mcp 与 pyyaml（均为可选依赖）
```

核心库**不强依赖** mcp / pyyaml；未安装时 `import mcs` 与既有功能不受影响（MCP 模块惰性导入）。

## 配置

MCP server 启动需要一个 [YAML 配置文件](configuration.md)（与库 / Python 用法同一条配置链，
含 preset 叠加、`${VAR}` 插值、import-path 插件、provenance 校验）。

**agent LLM 复用 MCS yaml**：mcs_mcp 从 `plugin_configs` 反推 agent chat LLM（识别
`{deepseek,ollama,claude}_llm` 键），**不新增 agent.yaml、不要求 `AGENT_LLM_*` env**。故 yaml 的
`plugin_configs` MUST 含上述之一段（否则启动早失败并提示）。配多个 `*_llm` 时按 `write_llm` 消歧。
> agent chat 需 tool-calling 能力的模型；deepseek-chat / claude-3-5-sonnet 等支持，选模型时留意。

```yaml
# mcs.yaml
preset: knowledge_graph
plugin_configs:
  deepseek_llm:
    api_key: ${DEEPSEEK_API_KEY}   # 秘密走环境、不进文件
  sqlite_storage:
    path: /data/mcs.db             # 持久化知识图谱
```

> ⚠️ 配置文件是**受信输入**：经 import-path 可加载任意代码，**勿接受陌生来源**（见
> [配置文件文档](configuration.md#安全须知受信输入)）。

## 运行

```bash
# 方式一：环境变量指定配置
export MCS_CONFIG=/path/to/mcs.yaml
mcs-mcp

# 方式二：CLI 参数
mcs-mcp --config /path/to/mcs.yaml
# 等价：python -m mcs_mcp
```

缺配置 / 文件不存在 / build 失败 → 清晰报错并以非零码退出。

## 暴露的工具

| 工具 | 入参 | 返回 |
|------|------|------|
| `query` | `query: str` | agent ReAct 多步探索后的**自然语言答复文本**（含 `[id:...]` 节点引用；偶发返回 agent 降级文本如「达到最大轮次」属正常、非错误） |
| `ingest` | `text: str` | **状态摘要**：抽取概念数 / 新增合并节点数 / 是否落盘（经 `agent.memory.learn`、不报边计数、不回原始对象） |

> 仅这两个工具经 `@mcp_server.tool()` 注册（与 `mcp-server` spec「含且仅含 query 与 ingest」一致）。
> 事件 / source 不再有独立工具——`ingest` 每次摄入即自动记一个时间轴事件（可选 source 切分），
> 见 [architecture.md](architecture.md) 写入 ⓪ 段。

## 接入 Claude Desktop

在 Claude Desktop 配置文件（macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`；
Windows: `%APPDATA%\Claude\claude_desktop_config.json`）中加：

```json
{
  "mcpServers": {
    "mcs": {
      "command": "mcs-mcp",
      "args": ["--config", "/absolute/path/to/mcs.yaml"],
      "env": {
        "DEEPSEEK_API_KEY": "sk-..."
      }
    }
  }
}
```

若 `mcs-mcp` 不在 PATH，用解释器的完整路径，例如
`/path/to/.venv/Scripts/mcs-mcp.exe`（Windows）或 `/path/to/.venv/bin/mcs-mcp`（macOS / Linux）。
也可以用 `python -m mcs_mcp`：`"command": "python"`、`"args": ["-m", "mcs_mcp", "--config", "..."]`。

## 须知

- **工具调用慢**：`query` 是 agent ReAct 多步探索（多轮 LLM 调用、耗时较长，建议客户端超时 ≥120s）；
  `ingest` 走 `memory.learn` 写图原语、不经 agent ReAct loop（仅 MCS 写管线的 LLM 抽取阶段用 LLM，
  比 `query` 快但仍非瞬时）。本期不强加超时 / 流式进度。
- **调用串行 / 线程亲和**：MCS 非线程安全（共享内存图）+ SQLite 连接绑创建线程，故 MCS 的构造与
  全部调用都经 `MemoryStore` 自带的**同一个单 worker 线程**（`max_workers=1`）——并发到达的工具调用
  在 MemoryStore 段被串行化（不交错），agent 的 LLM 调用段可并发；mcs_mcp 外层仅 `asyncio.to_thread`
  桥，不阻塞 stdio 事件循环。
- **单进程 / 单库**：stdio 单客户端。多租户 / 远程 / 并发多客户端不在本期范围（留后续）。
- **配置受信**：沿用 [config-file-loading](configuration.md) 的受信输入约束。

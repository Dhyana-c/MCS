# MCP Server

> 把 MCS 作为 **MCP（Model Context Protocol）server** 暴露，让 Claude Desktop 等客户端
> 把知识图谱当工具用：`query` 查询、`ingest` 摄入。传输用 **stdio**（本地标准）。

## 安装

```bash
pip install -e ".[mcp]"   # 安装 mcp 与 pyyaml（均为可选依赖）
```

核心库**不强依赖** mcp / pyyaml；未安装时 `import mcs` 与既有功能不受影响（MCP 模块惰性导入）。

## 配置

MCP server 启动需要一个 [YAML 配置文件](configuration.md)（与库 / Python 用法同一条配置链，
含 preset 叠加、`${VAR}` 插值、import-path 插件、provenance 校验）。

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
| `query` | `query: str` | 相关节点与关系边的**可读文本**（`Subgraph` 经 `render_facts` 渲染；若 postprocess 已转字符串则透传） |
| `ingest` | `text: str` | **状态摘要**：抽取概念数 / 新增合并节点数 / 是否落盘（不报边计数、不回原始对象） |

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

- **工具调用慢**：`query` / `ingest` 每次都是**多轮 LLM 调用**，不瞬时。客户端别配过短超时；
  本期不强加超时 / 流式进度。
- **调用串行**：MCS 非线程安全（共享内存图）+ SQLite 连接绑创建线程，故 MCS 的构造与全部调用
  都经**同一个单 worker 线程**（`ThreadPoolExecutor(max_workers=1)`）。并发到达的工具调用被串行化
  （`ingest` 与 `query` 不交错）；慢调用不阻塞 stdio 事件循环。
- **单进程 / 单库**：stdio 单客户端。多租户 / 远程 / 并发多客户端不在本期范围（留后续）。
- **配置受信**：沿用 [config-file-loading](configuration.md) 的受信输入约束。

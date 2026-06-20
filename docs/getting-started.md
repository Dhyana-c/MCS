# 上手指南

> 5 分钟从零跑通 MCS：安装 → 创建实例 → 写入 → 查询 → 持久化 → MCP 接入 → Agent 启动。
> 更深的概念见 [architecture.md](architecture.md) 与 [graph-model-design.md](graph-model-design.md)。

## 1. 安装

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS / Linux
pip install -e ".[dev]"
```

可选依赖按需装：`.[claude]`（Claude 后端）、`.[mcp]`（MCP server）、`.[yaml]`（YAML 配置）。

## 2. 创建实例

最简单的方式是 `create_mcs()` 快捷工厂：

```python
from mcs.presets import create_mcs

# 知识图谱模式（默认 Phase 1 插件链）。需先设置环境变量 DEEPSEEK_API_KEY，
# 或在 plugin_configs 里传 api_key。
mcs = create_mcs(llm="deepseek", db_path="mcs.db")
```

需要完整控制时改用 Builder：

```python
from mcs.entities.config import MCSConfig
from mcs.presets import Phase1Builder

config = MCSConfig.knowledge_graph(write_llm="deepseek", read_llm="deepseek")
config.plugin_configs["deepseek_llm"]["api_key"] = "your-api-key"
mcs = Phase1Builder(config).build()    # 返回即用的 MCS 实例
```

> **不带 API key 跑通**：`examples/basic_usage.py` 默认走 mock 模式（脚本化 LLM、不联网、无需 key）。
> 想先验证接线，直接 `python examples/basic_usage.py`。

## 3. 写入（ingest）

`ingest()` 走写入管线：**每次把整个输入记为一个事件节点**（记录这一行为、落用户时间轴）→ 抽 `content`
的概念 / 命题、对齐已有节点、判关系与互斥 → 事件 / source 对抽出节点连背书边 → 守门、落盘。
入参 `str | IngestInput`——纯文本最简：

```python
mcs.ingest("深度学习是机器学习的一个子领域，使用多层神经网络来学习数据的表示。")
mcs.ingest("卷积神经网络是一种专门处理网格状数据的深度学习模型。")
```

需要带**记录时间 / 出处资料**时，传结构化 `IngestInput`（timestamp / source 由规则消费、**只有 content 走 LLM**）：

```python
from mcs.entities import IngestInput, SourceData

mcs.ingest(IngestInput(
    content="今天读了一篇 CNN 综述。",          # 唯一进 LLM 抽取的字段
    timestamp="2026-06-20T10:00:00",            # 记录时间（缺省取 now）
    source=SourceData(                          # 可选：按规则切分为 source 节点（不经 LLM）
        name="cnn_survey.pdf", source_type="file",
        chunks=[{"content": "第一段", "chunk_index": 0}],
    ),
))
```

> 事件 / source **只能经 `ingest` 产生**——每次摄入自动记一个时间轴事件（带 `timestamp`），可选
> `source` 按规则切分为 source 节点，二者都对本次抽出的概念 / 事实连背书边。没有独立的
> `ingest_event` / `ingest_source` 入口。

## 4. 查询（query）

`query()` 默认返回一个 **`Subgraph`**（选中的节点 + 选中的 `关联` / `互斥` 边），不是自然语言答案：

```python
result = mcs.query("什么是深度学习？")

for node in result.nodes:
    print(node.name, "—", node.content[:80])

for edge in result.edges:               # 关联 / 互斥 边
    print(f"{edge.source_id} —{edge.type}→ {edge.target_id}")
```

> 想要自然语言答案？挂一个 `POSTPROCESS` 插件把 `Subgraph` 合成成字符串，或把节点交给上层 LLM 自行合成。

## 5. 持久化

默认 `auto_persist=True`，使用 SQLite：每次 `ingest()` 后自动增量落盘到 `db_path`。下次用同一路径
`build()` 时自动加载已有图——无需手动 save / load。

```python
mcs = create_mcs(llm="deepseek", db_path="mcs.db")   # 复用上次的图
mcs.shutdown()                                        # 退出前关闭插件与存储
```

## 6. 作为 MCP Server

把 MCS 暴露成 MCP（stdio）server，供 Claude Desktop 等客户端把知识图谱当工具用（`query` / `ingest`）：

```bash
pip install -e ".[mcp]"
export MCS_CONFIG=/path/to/mcs.yaml      # YAML 配置见 configuration.md
mcs-mcp                                   # 或 python -m mcs_mcp
```

详见 [mcp-server.md](mcp-server.md)。

## 7. 启动记忆 Agent

`mcs_agent` 是一个带对话界面的 ReAct 记忆助手（自有 LLM + 5 个导航工具 + FastAPI + 前端可视化）：

```bash
export MCS_CONFIG=/path/to/mcs.yaml       # MCS 图配置
export AGENT_LLM_API_KEY=sk-...           # agent 自有 LLM（openai 兼容端点）
export AGENT_LLM_MODEL=deepseek-chat
# export AGENT_LLM_BASE_URL=...           # 可选，自定义端点
python -m mcs_agent                        # 默认起在 http://127.0.0.1:8000
```

浏览器打开 `http://127.0.0.1:8000` 即见对话 + 图谱可视化。详见 [memory-agent.md](memory-agent.md)。

## 下一步

- [architecture.md](architecture.md) — 系统全景、双层结构、读写管线
- [plugin-system.md](plugin-system.md) — 用插件扩展能力
- [api-reference.md](api-reference.md) — 公开方法与数据类速查
- [configuration.md](configuration.md) — 用 YAML 配置而不是写 Python
- [faq.md](faq.md) — 常见问题

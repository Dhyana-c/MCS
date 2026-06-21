# MCS - Maximum-Context Subgraph

一个**可扩展的记忆系统**——面向单一领域，由大模型语义驱动，把零散文本组织成图结构的语义记忆。不依赖 embedding / 向量检索，靠大模型直接阅读"装得下的局部子图"完成关系发现、聚类与召回。

MCS 默认返回相关节点集合（`List[Node]`），不是自然语言答案。它专注于"记忆本身"，把合成答案、多轮对话、追问加深等留给上层（RAG / Agent / Chatbot）。

## 核心赌注

**知识有足够的局部性**——回答一个问题所需要的概念，在图里彼此靠近，几跳语义游走就能连到一起。

这对"已能被人类整理成可教结构的领域"（物理、工程、各类有教科书/本体的学科）最成立；对跨领域综合、强语境依赖、矛盾常态化的知识（法律、历史、文化）会发紧。

## 快速开始

### 安装

```bash
python -m venv .venv
.venv\Scripts\activate          # Windows
# source .venv/bin/activate     # macOS / Linux
pip install -e ".[dev]"
```

### 基本用法

```python
from mcs.presets import create_mcs

# 知识图谱模式（默认配置含 Phase 1 插件）
mcs = create_mcs(llm="deepseek", db_path="mcs.db")
# 需先设置环境变量 DEEPSEEK_API_KEY 或传入 plugin_configs

# 摄入文本 → 自动抽概念、定位、入图
mcs.ingest("深度学习是机器学习的一个子领域，它使用多层神经网络来学习数据的表示。")
mcs.ingest("卷积神经网络是一种专门处理网格状数据的深度学习模型。")

# 查询 → 默认返回相关节点集合
nodes = mcs.query("什么是深度学习？")
for n in nodes:
    print(n.name, "—", n.content[:80])
```

或使用 Builder 完整自定义：

```python
from mcs.presets import Phase1Builder
from mcs.entities.config import MCSConfig

config = MCSConfig.knowledge_graph(write_llm="deepseek", read_llm="deepseek")
config.plugin_configs["deepseek_llm"]["api_key"] = "your-api-key"

builder = Phase1Builder(config)
mcs = builder.build()  # 返回即用的 MCS 实例
```

### 配置文件（YAML）

也支持从 **YAML 文件**配置（preset 铺底 + 字段叠加 + `${VAR}` 环境变量插值 + import-path 第三方插件）：

```bash
pip install -e ".[yaml]"   # 可选依赖 PyYAML
```

```yaml
# mcs.yaml
preset: knowledge_graph          # 复用默认 Phase1 插件集，只覆盖要改的字段
write_llm: deepseek
plugin_configs:
  deepseek_llm:
    api_key: ${DEEPSEEK_API_KEY}  # 秘密走环境、不进文件
  sqlite_storage:
    path: mcs.db
shared_plugins:
  - my_pkg.exts:MyEdgeExtension   # import-path 第三方插件
```

```python
from mcs.entities.config import MCSConfig
from mcs.presets import Phase1Builder

config = MCSConfig.from_file("mcs.yaml")
mcs = Phase1Builder(config).build()
```

> ⚠️ 配置文件是**受信输入**：YAML 经 import-path 可加载任意代码，**勿接受陌生来源**。
> 自定义 LLM 必须走**无 preset** 路径（`knowledge_graph()` 只认 deepseek/claude/ollama）。
> 详见 [配置文件文档](docs/configuration.md)。

### 切换后端

<details>
<summary>Claude / Anthropic 后端</summary>

```python
mcs = create_mcs(
    llm="claude",
    db_path="mcs.db",
    plugin_configs={
        "claude_llm": {
            "auth_token": "your-anthropic-token",
            "model": "claude-3-5-sonnet-latest",
            "base_url": "https://api.anthropic.com",
        }
    }
)
```

需先安装：`pip install -e ".[claude]"`

</details>

<details>
<summary>Ollama 本地后端（零 token 成本）</summary>

```python
mcs = create_mcs(
    llm="ollama",
    db_path="mcs.db",
    plugin_configs={
        "ollama_llm": {
            "base_url": "http://localhost:11434/v1",
            "model": "qwen3.5:9b",
        }
    }
)
```

前置条件：安装 Ollama → `ollama serve` → `ollama pull qwen3.5:9b`

适用场景：大量实验迭代、离线/隐私场景。小模型结构化 JSON 可靠性弱于云端，但 lenient parser 已缓解。

</details>

<details>
<summary>不带 API key 跑通</summary>

`examples/basic_usage.py` 和 `examples/wiki_example.py` 默认走 mock 模式（不需要 API key、不联网）。

```bash
python examples/basic_usage.py
# 或加真实 LLM:
# MCS_LLM_MODE=real DEEPSEEK_API_KEY=sk-... python examples/basic_usage.py
```

</details>

## 作为 MCP Server

MCS 可作为 **MCP（stdio）server** 暴露 `query` / `ingest` 工具，供 Claude Desktop 等客户端把知识图谱当工具用：

```bash
pip install -e ".[mcp]"          # 可选依赖 mcp + pyyaml
export MCS_CONFIG=/path/to/mcs.yaml   # YAML 配置（见「配置文件」）
mcs-mcp                          # 或 python -m mcs_mcp
```

```json
// Claude Desktop: claude_desktop_config.json
{
  "mcpServers": {
    "mcs": { "command": "mcs-mcp", "args": ["--config", "/abs/path/mcs.yaml"],
             "env": { "DEEPSEEK_API_KEY": "sk-..." } }
  }
}
```

> 工具调用慢（多轮 LLM）、调用串行（MCS 非线程安全）。详见 [MCP Server 文档](docs/mcp-server.md)。

## 文档

| 文档 | 说明 |
|------|------|
| [文档索引](docs/INDEX.md) | 所有文档的统一导航入口 |
| [上手指南](docs/getting-started.md) | 5 分钟跑通：安装 → 写入 → 查询 → MCP → Agent |
| [架构总览](docs/architecture.md) | 系统定位、双层结构、核心不变量、插件体系 |
| [图模型设计](docs/graph-model-design.md) | 完整、权威的图模型与核心算法设计 |
| [常见问题](docs/faq.md) | FAQ |

## 评测

MCS 使用 MultiHop-RAG 做文档级多跳检索评测，指标为 Hit@k / MAP@k / MRR@k。

**最新结果**（609 篇 whole-doc 建图、200 query、DeepSeek 后端，`T=16K`）：**hit@10 ≈ 0.70 / recall@10 ≈ 0.39**（分类型 inference 0.74 / temporal 0.69 / comparison 0.67）。

> ⚠️ 当前 hit@10 的最大制约是**跨语言**：建图摘要由 LLM 生成为中文，而 query 为英文，词法交集近零。反事实对照（body 换英文原文、零 LLM）可达 ~0.84——说明瓶颈在语言对齐与下游重排，而非图模型 / 召回链路本身（全节点 gold 召回 0.89+）。详见 [评测报告](bench/multihop_rag/REPORT.md)。

下方命令为 200 篇子集的**快速上手**（配置与上述权威数字不同，不直接对应该数字）：

```bash
# 200 篇子集，DeepSeek 后端（相关性重排默认开）
python -m bench.multihop_rag --llm deepseek --corpus-subset 200 --output ./mh_out
```

详见 [bench/README.md](bench/README.md)。

## 贡献

欢迎贡献！请阅读 [CONTRIBUTING.md](CONTRIBUTING.md) 了解环境搭建、开发流程和提交规范。

## 许可证

本项目基于 [MIT 许可证](LICENSE) 开源。

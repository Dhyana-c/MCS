## Why

MCS 要做成 **MCP server**，让 Claude 这类客户端把知识图谱当工具用。地基（`config-file-loading`）已就位，MCP 本身是**薄适配层**：读配置 → build 出 MCS → 把 `ingest` / `query` 包成 MCP 工具。

现状（已核实）：

- MCS 公开面极小：`ingest(text, **metadata) -> WriteContext`（[mcs.py:56](mcs/core/mcs.py:56)）、`query(text, existing_context=None) -> Subgraph`（[mcs.py:60](mcs/core/mcs.py:60)，**默认返回 `Subgraph`（nodes + 选中事实边），但 postprocess 插件 MAY 转成字符串**）、`shutdown()`。
- 构造已可从文件来（本变更**依赖** `config-file-loading` 先落地）。
- MCS **非线程安全**：SQLite 连接默认 `check_same_thread=True`（绑定创建线程）、ingest 改图 / query 读图共享内存图状态。
- `ingest` / `query` 每次都是**多轮 LLM 调用**，天生不瞬时。

## What Changes

- **新增 MCP server 模块**（`mcs/mcp/server.py` + 入口）：启动时从 `MCS_CONFIG` 环境变量（或 CLI 参数）指向的 YAML 经 `MCSConfig.from_file` build 出 MCS；缺配置 / build 失败 MUST 清晰报错退出。
- **暴露两个工具**（用户已选 query + ingest）：
  - `query(query: str) -> str`：跑 `mcs.query`，**结果渲染为 LLM 可读文本**——`Subgraph` 经 `ContextRenderer.render_facts(nodes, edges, mode=relation_model)` 渲染；若 postprocess 已返回字符串则直接透传。
  - `ingest(text: str) -> str`：跑 `mcs.ingest`，返回**简明状态摘要**（从 `WriteContext` 取：抽取概念数 `len(concepts)`、新增/合并节点数 `len(changed)`、`persisted`）。**不含边计数**——`WriteContext` 无边计数字段，`decisions[].edges_to` 是请求边、非实际落地（fanout 会增删边）。**不**回原始 `WriteContext`。
- **调用串行化 + 线程亲和**（正确性硬约束）：MCS 非线程安全 + SQLite 连接绑创建线程，故 MCS 的**构造与全部调用都经同一个单 worker 线程**（单线程 executor `ThreadPoolExecutor(max_workers=1)`）——单 worker 本身即串行（ingest 与 query 不交错），且 SQLite 始终在创建它的线程访问、不触发 `check_same_thread` 报错。**关键是 executor 的单线程亲和、不是锁**：锁只保证互斥、不保证同线程，持锁跨线程访问 SQLite 仍崩。MCS 调用经 executor `await`、不阻塞 stdio 事件循环。
- **打包与传输**：`mcp` + `PyYAML` 作可选依赖 `[mcp]` extra；加 console 入口 `mcs-mcp`（`python -m mcs.mcp` 亦可）；传输用 **stdio**（本地 MCP 标准，Claude Desktop 直接拉起）。
- **错误隔离**：单次工具调用异常 → 返回 MCP 错误响应，server MUST NOT 崩溃。

**OUT OF SCOPE（明确不做）**：

- **HTTP / SSE 传输**——本期只 stdio；远程传输留后续。
- **结构化（JSON）query 返回 / 流式进度 / 取消**——本期 query 回渲染文本、ingest 回状态串；结构化与流式留后续。
- **认证 / 多租户 / 并发多客户端**——stdio 单客户端、调用串行；并发场景留后续。
- **暴露 `query` 的 `existing_context` 等高级参数 / 管理类工具（重置、统计）**——本期工具面最小化。
- **改 MCS 核心 / builder / config**——MCP 是纯消费方，只读用既有公开面 + `config-file-loading`。

依赖：本变更 **MUST 在 `config-file-loading` 之后**实施（复用 `MCSConfig.from_file`）。

## Capabilities

### New Capabilities

- `mcp-server`：把 MCS 作为 MCP（stdio）server 暴露 `query` / `ingest` 工具；从 `MCS_CONFIG` 配置 build；结果渲染为文本；调用串行化 + 线程亲和；`mcp` 可选依赖与 `mcs-mcp` 入口。

## Impact

- **新增** (`mcs/mcp/server.py`、`mcs/mcp/__init__.py`)：server 装配、工具定义、序列化执行器、结果渲染。
- **打包** (`pyproject.toml`)：`[project.optional-dependencies] mcp = ["mcp>=1.0", "pyyaml>=6"]`；`[project.scripts] mcs-mcp = "mcs.mcp.server:main"`。
- **渲染复用** (`mcs/core/context_renderer.py`)：query 结果走现成 `render_facts`（**不改其代码**，只调用）。
- **文档** (`docs/`、`README.md`)：MCP 安装（`pip install mcs[mcp]`）、`MCS_CONFIG` 配置、Claude Desktop 接入示例、"工具调用慢 / 串行"与"配置受信"须知。
- **测试** (`tests/`)：工具处理函数单测（从配置 build、query 渲染 Subgraph→文本、postprocess 字符串透传、ingest 状态摘要、串行锁、缺配置报错、工具异常隔离）；MCP 传输层 smoke（用 MCP SDK 内存传输，若可行）。

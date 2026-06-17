## Context

MCS 做成 MCP server，让客户端把知识图谱当工具。地基 `config-file-loading` 已就位，MCP 是薄适配：读配置 → build MCS → 暴露 `ingest` / `query`。

已核实约束：MCS 公开面 = `ingest(text)->WriteContext` / `query(text)->Subgraph`（postprocess 可转 str）/ `shutdown()`；MCS **非线程安全**（SQLite `check_same_thread=True` 绑创建线程、共享内存图）；`ingest`/`query` 多轮 LLM、慢。

本变更**依赖** `config-file-loading`，且只消费 MCS 既有公开面——**不改核心 / builder / config**。

关键模块：新增 `mcs/mcp/`、`MCSConfig.from_file`（依赖件）、`MCS.ingest/query/shutdown`、`ContextRenderer.render_facts`、`pyproject.toml`。

## Goals / Non-Goals

**Goals**
- stdio MCP server，从 `MCS_CONFIG` 指向的 YAML build MCS，暴露 `query` / `ingest`。
- query 结果渲染为 LLM 可读文本；ingest 回简明状态。
- 调用串行化 + 线程亲和，保证 MCS 非线程安全下的正确性。
- `mcp` 可选依赖、`mcs-mcp` 入口；不改 MCS 核心。

**Non-Goals（本期不做）**
- HTTP/SSE；结构化 / 流式 / 取消；认证 / 多租户 / 并发多客户端；管理类工具；暴露高级查询参数。

## Decisions

### D1：薄适配，复用 config-file-loading

- server 启动：读 `MCS_CONFIG`（或 `--config` CLI 参数）→ `MCSConfig.from_file(path)` → `Phase1Builder(config).build()` → 持有 MCS。缺配置 / 文件不存在 / build 失败 MUST 清晰报错并非零退出。
- **备选**：MCP 自带一套独立配置。**否决**——与 `config-file-loading` 重复；MCP 就该复用同一条配置链（含 provenance、env 插值、import-path）。

### D2：工具面最小（query + ingest）

- `query(query: str) -> str`、`ingest(text: str) -> str`。不暴露 `existing_context`、不加管理类工具。
- **备选**：暴露全部参数 / 加 reset、stats 等。**否决**——对 LLM 客户端无意义、扩大攻击面与误用面；最小工具面更稳。

### D3：query 结果 → 文本

- `mcs.query` 返回 `Subgraph`（nodes + edges）时，经 `ContextRenderer.render_facts(nodes, edges, mode=relation_model)` 渲染为文本；若 postprocess 已返回 `str`（如 synthesize）则**直接透传**。
- `relation_model` 从已 build 的配置取（与 store 同模式）。
- **备选**：返回结构化 JSON（节点 / 边数组）。**否决**——LLM 客户端要的是可读文本；结构化输出留后续（可作另一个工具或参数）。

### D4：ingest 回简明状态、非 WriteContext

- `ingest` 返回状态串，数据源是 `WriteContext` 真有的字段：`len(changed)`（新增/合并节点）、`len(concepts)`（抽取概念）、`persisted`。**无边计数**——`WriteContext` 无该字段，`decisions[].edges_to` 是请求边、非实际落地（fanout 裂变/合并会增删边），要准须 store 前后快照（侵入式，本期不做）。返回如"已写入：N 概念、节点 +M、persisted=✓"。
- **备选**：回原始 `WriteContext`。**否决**——对 LLM 无意义、可能巨大、泄漏内部结构。

### D5：调用串行化 + 线程亲和（正确性硬约束）

- MCS 非线程安全 + SQLite 连接绑创建线程。设计：**单一 worker 线程**（单线程 executor `ThreadPoolExecutor(max_workers=1)`）既 build MCS、又执行全部工具调用；MCP 异步处理器把每次调用 `await` 丢给该 executor。**单 worker 本身即串行、不需额外锁**——锁只互斥、不保证同线程，持锁跨线程访问 SQLite 仍崩；关键是 executor 的单线程亲和。由此：① 调用串行（ingest 与 query 不交错）；② MCS / SQLite 始终在同一线程访问（不触发 `check_same_thread`）；③ 慢 LLM 不阻塞 stdio 事件循环。
- **备选 1**：每次调用新开 SQLite 连接 / `check_same_thread=False` 裸用 / 仅加锁。**否决**——绕过线程检查（或仅互斥锁）仍有内存图状态竞态（ingest 改图 / query 读图），且锁不保证同线程；治标不治本。单线程 executor 一招解决串行 + 线程亲和。
- **备选 2**：直接在事件循环里同步调 MCS。**否决**——多轮 LLM 阻塞整个 server、stdio 卡死。

### D6：stdio 传输 + 可选依赖 + 入口

- 传输 stdio（本地 MCP 标准；Claude Desktop 用 command+args 拉起）。
- `pyproject.toml`：`[mcp]` extra = `["mcp>=1.0", "pyyaml>=6"]`（MCP server 必然要读 YAML 配置，故捆 PyYAML）；`[project.scripts] mcs-mcp = "mcs.mcp.server:main"`。
- **备选**：HTTP/SSE。**否决**——本地集成 stdio 是标准、零网络配置；远程留后续。

### D7：错误隔离 + 慢调用须知

- 单次工具调用异常 MUST 捕获 → 返回 MCP 错误响应，server MUST NOT 崩。
- `ingest`/`query` 多轮 LLM、慢——文档写明客户端别配过短超时；本期**不**强加超时 / 流式进度（留后续）。
- **配置受信**沿用 `config-file-loading` 须知（import-path 可加载任意代码）。

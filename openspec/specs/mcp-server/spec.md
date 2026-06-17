# mcp-server Specification

## Purpose
TBD - created by archiving change mcp-server. Update Purpose after archive.
## Requirements
### Requirement: 从配置构建并启动 MCP server

系统 SHALL 提供 MCP（stdio）server 入口，启动时从 `MCS_CONFIG` 环境变量（或 `--config` CLI 参数）指向的 YAML 经 `MCSConfig.from_file` + builder build 出 MCS 后开始服务。配置缺失 / 文件不存在 / build 失败 MUST 清晰报错并以非零码退出。进程退出 MUST 调用 `mcs.shutdown()`（含异常路径）。

#### Scenario: 从 MCS_CONFIG 构建

- **WHEN** 设置 `MCS_CONFIG` 指向有效 YAML 并启动 server
- **THEN** MUST 经 `MCSConfig.from_file` build 出 MCS 并进入服务态

#### Scenario: 缺配置清晰退出

- **WHEN** 未设 `MCS_CONFIG` 且未给 `--config`
- **THEN** MUST 报清晰错误并非零退出；MUST NOT 以无效状态启动

---

### Requirement: 暴露 query 与 ingest 工具

server SHALL 暴露两个 MCP 工具：`query(query: str) -> str` 与 `ingest(text: str) -> str`。本期 MUST NOT 暴露其他工具或高级参数（如 `existing_context`）。

#### Scenario: 列出工具

- **WHEN** 客户端 list tools
- **THEN** MUST 含且仅含 `query` 与 `ingest`（各带描述与字符串入参 schema）

---

### Requirement: query 结果渲染为 LLM 可读文本

`query` 工具 SHALL 把 `mcs.query` 的结果转为文本返回：结果为 `Subgraph`（nodes + edges）时经 `ContextRenderer.render_facts(nodes, edges, mode=relation_model)`（`relation_model` 取自当前配置）渲染；结果已是字符串（postprocess 转换）时 MUST 直接透传。MUST NOT 返回原始对象 / 内部结构。

#### Scenario: Subgraph 渲染为文本

- **WHEN** `mcs.query` 返回 `Subgraph`
- **THEN** 工具 MUST 返回经 `render_facts` 渲染、含其节点与选中关系边的文本

#### Scenario: 字符串结果透传

- **WHEN** postprocess 已把 query 结果转为字符串
- **THEN** 工具 MUST 原样返回该字符串、MUST NOT 再包装

---

### Requirement: ingest 返回简明状态摘要

`ingest` 工具 SHALL 返回简明状态摘要，数据源为 `WriteContext` 真有的字段（`len(changed)` 新增/合并节点、`len(concepts)` 抽取概念、`persisted`）。MUST NOT 返回原始 `WriteContext`；MUST NOT 报边计数（`WriteContext` 无边计数字段，`decisions[].edges_to` 是请求边、非实际落地）。

#### Scenario: ingest 回状态

- **WHEN** 调用 `ingest(text)` 成功
- **THEN** 返回值 MUST 是含写入概要（节点 / 概念计数、`persisted`）的简短字符串；MUST NOT 是原始 `WriteContext`；MUST NOT 含边计数

---

### Requirement: 工具调用串行化与线程亲和

因 MCS 非线程安全（共享内存图）且 SQLite 连接绑定创建线程，server SHALL 把 MCS 的构造与全部调用置于**同一个单 worker 线程**（单线程 executor，`max_workers=1`）。单 worker 本身即串行，SHALL NOT 依赖锁达成线程亲和（锁只互斥、不保证同线程）。并发到达的工具调用 MUST 串行执行（`ingest` 与 `query` 不交错）；MCS 调用 MUST 不阻塞 stdio 事件循环。

#### Scenario: 并发调用被串行化

- **WHEN** 两次工具调用几乎同时到达
- **THEN** 二者对 MCS 的访问 MUST 串行（不交错）；MUST NOT 并发改 / 读同一图状态

#### Scenario: MCS 访问线程一致

- **WHEN** server 处理任意工具调用
- **THEN** 对 MCS / SQLite 的访问 MUST 发生在构造 MCS 的同一线程；MUST NOT 触发 SQLite 跨线程错误

#### Scenario: 慢调用不阻塞事件循环

- **WHEN** 一次 `ingest`/`query` 正在跑多轮 LLM（耗时）
- **THEN** stdio 事件循环 MUST 不被阻塞（调用在 worker 执行）

---

### Requirement: 单次工具异常隔离

单次工具调用抛异常 SHALL 被捕获并转为 MCP 错误响应；server MUST NOT 因此崩溃，MUST 能继续服务后续调用。

#### Scenario: 工具异常不崩 server

- **WHEN** 某次 `query` / `ingest` 内部抛异常
- **THEN** 客户端 MUST 收到错误响应（含简明原因）；server MUST 仍可处理下一次调用

---

### Requirement: MCP 为可选依赖、stdio 传输与入口

MCP server 所需的 `mcp` 与 `PyYAML` SHALL 为可选依赖（`[mcp]` extra），核心库 MUST NOT 强制依赖。server SHALL 用 stdio 传输，并提供 `mcs-mcp` 控制台入口。`mcp` 缺失时入口 MUST 报含安装指引（`pip install mcs[mcp]`）的清晰错误。

#### Scenario: 缺 mcp 给安装指引

- **WHEN** 未安装 `mcp` 时运行 `mcs-mcp`
- **THEN** MUST 报错且提示安装 `mcs[mcp]`；MUST NOT 是裸 ImportError 无指引

#### Scenario: 核心库不因 MCP 受影响

- **WHEN** 未安装 `mcp` / `PyYAML`
- **THEN** `import mcs` 与既有功能 MUST 不受影响（MCP 模块惰性 / 隔离导入）


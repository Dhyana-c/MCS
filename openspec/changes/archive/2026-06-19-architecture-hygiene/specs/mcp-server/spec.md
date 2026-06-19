## MODIFIED Requirements

### Requirement: MCP 为可选依赖、stdio 传输与入口

MCP server SHALL 作为**顶层独立包 `mcs_mcp`** 提供（不再内嵌于核心库 `mcs/`，与 `mcs_agent` 应用包对称）。其所需的 `mcp` 与 `PyYAML` SHALL 为可选依赖（`[mcp]` extra），核心库 MUST NOT 强制依赖。server SHALL 用 stdio 传输，并提供 `mcs-mcp` 控制台入口（目标 `mcs_mcp.server:main`）与 `python -m mcs_mcp` 启动方式。`mcp` 缺失时入口 MUST 报含安装指引（`pip install mcs[mcp]`）的清晰错误。

#### Scenario: 顶层包与入口

- **WHEN** 启动 MCP server
- **THEN** MUST 可经 `mcs-mcp` console 入口或 `python -m mcs_mcp` 启动
- **AND** server 代码 MUST 位于顶层包 `mcs_mcp`，MUST NOT 位于 `mcs/mcp`

#### Scenario: 缺 mcp 给安装指引

- **WHEN** 未安装 `mcp` 时运行 `mcs-mcp`
- **THEN** MUST 报错且提示安装 `mcs[mcp]`；MUST NOT 是裸 ImportError 无指引

#### Scenario: 核心库不因 MCP 受影响

- **WHEN** 未安装 `mcp` / `PyYAML`
- **THEN** `import mcs` 与既有功能 MUST 不受影响
- **AND** 因 `mcs_mcp` 在核心库之外，`import mcs` MUST NOT 触及任何 mcp 相关模块

---

### Requirement: query 结果渲染为 LLM 可读文本

`query` 工具 SHALL 把 `mcs.query` 的结果转为文本返回，渲染委托核心库 `mcs.rendering.render_query_result`（`relation_model` 取自当前配置）：结果为 `Subgraph` 时经 `ContextRenderer.render_facts` 渲染；结果已是字符串（postprocess 转换）时 MUST 直接透传。MUST NOT 返回原始对象 / 内部结构，MUST NOT 在 server 内重复实现渲染逻辑。

#### Scenario: Subgraph 渲染为文本

- **WHEN** `mcs.query` 返回 `Subgraph`
- **THEN** 工具 MUST 经 `mcs.rendering.render_query_result` 返回含其节点与选中关系边的文本

#### Scenario: 字符串结果透传

- **WHEN** postprocess 已把 query 结果转为字符串
- **THEN** 工具 MUST 原样返回该字符串、MUST NOT 再包装

---

### Requirement: ingest 返回简明状态摘要

`ingest` 工具 SHALL 返回简明状态摘要，渲染委托核心库 `mcs.rendering.format_ingest_status`，数据源为 `WriteContext` 真有的字段（`len(changed)` 新增/合并节点、`len(concepts)` 抽取概念、`persisted`）。MUST NOT 返回原始 `WriteContext`；MUST NOT 报边计数；MUST NOT 在 server 内重复实现该摘要逻辑。

#### Scenario: ingest 回状态

- **WHEN** 调用 `ingest(text)` 成功
- **THEN** 返回值 MUST 是含写入概要（节点 / 概念计数、`persisted`）的简短字符串；MUST NOT 是原始 `WriteContext`；MUST NOT 含边计数

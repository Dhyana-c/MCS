# mcp-server（delta）

> `relation_model` 删除后，渲染委托不再取 / 传该参数。

## MODIFIED Requirements

### Requirement: query 结果渲染为 LLM 可读文本

`query` 工具 SHALL 把 `mcs.query` 的结果转为文本返回，渲染委托核心库 `mcs.rendering.render_query_result`：结果为 `Subgraph` 时经 `ContextRenderer.render_facts` 渲染；结果已是字符串（postprocess 转换）时 MUST 直接透传。MUST NOT 返回原始对象 / 内部结构、MUST NOT 在 server 内重复实现渲染逻辑、MUST NOT 依赖 `relation_model`（已删除）。

#### Scenario: Subgraph 渲染为文本

- **WHEN** `mcs.query` 返回 `Subgraph`
- **THEN** 工具 MUST 经 `mcs.rendering.render_query_result` 返回含其节点与选中关系边的文本

#### Scenario: 字符串结果透传

- **WHEN** postprocess 已把 query 结果转为字符串
- **THEN** 工具 MUST 原样返回该字符串、MUST NOT 再包装

## MODIFIED Requirements

### Requirement: MemoryStore 复用共享渲染纯函数

`MemoryStore` SHALL 复用核心库 `mcs.rendering` 的公开纯函数 `render_query_result`（associate）与 `format_ingest_status`（learn）渲染结果，不重复实现。MUST NOT 引用任何应用包（如 `mcs_mcp`）的内部 / 私有函数。

#### Scenario: 复用而非重复实现

- **WHEN** `MemoryStore` 渲染 associate / learn 结果
- **THEN** MUST 调用 `mcs.rendering` 的公开渲染函数
- **AND** MUST NOT 自行实现等价渲染逻辑

#### Scenario: 不跨应用引用私有函数

- **WHEN** 检查 `mcs_agent` 的 import
- **THEN** MUST NOT 出现 `from mcs_mcp...` 或 `from mcs.mcp...` 的渲染函数引用
- **AND** 渲染函数 MUST 来自核心库 `mcs.rendering`

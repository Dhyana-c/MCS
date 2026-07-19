# memory-agent delta — associate neighbors 默认模式

## MODIFIED Requirements

### Requirement: MemoryStore 复用共享渲染纯函数

`MemoryStore` SHALL 复用核心库 `mcs.rendering` 的公开纯函数 `render_query_result`（associate 的 **`mcs` 模式**）与 `format_ingest_status`（learn）渲染结果，不重复实现。associate 的 **`neighbors` 模式**（默认）SHALL 用 MemoryStore 自有的节点列表渲染（含 `[id:...]` 存根、name==content 只写一份口径），MUST NOT 调用查询管线。MUST NOT 引用任何应用包（如 `mcs_mcp`）的内部 / 私有函数。

#### Scenario: mcs 模式渲染复用

- **WHEN** `MemoryStore` 以 `mode="mcs"` 渲染 associate 结果 / 渲染 learn 结果
- **THEN** MUST 分别经 `render_query_result` / `format_ingest_status`（核心库公开纯函数）

#### Scenario: neighbors 模式零管线

- **WHEN** `MemoryStore` 以 `mode="neighbors"`（默认）执行 associate
- **THEN** MUST NOT 调用 `mcs.query` / 查询管线，MUST NOT 产生任何 LLM 调用；渲染 MUST 含每个邻居的 `[id:...]` 存根

### Requirement: associate 原语（联想扩展）

`MemoryStore.associate(seed_id, mode)` 的默认 mode SHALL 为 `neighbors`：经 `store.get_relations(seed)` 取种子作任一端的 `关联` / `互斥` 边、渲染**一跳邻居**（纯图读、零 LLM）——相关性判断归 agent 的多轮探索（工具内 MUST NOT 嵌套 BFS / LLM 筛选）。载重双类过滤（同 universe 事件边核心侧单向、跨 universe 双向）由 `get_relations` 天然继承。**互斥邻居 SHALL 单列在前**（信号强）。邻居数 SHALL 按 `limit`（默认 60）截断，超出 MUST 标注总数与"可对具体邻居继续 associate 下钻"。`mode="mcs"` SHALL 保留旧行为（`mcs.query("", existing_context=[种子], universe=种子.universe)` 全管线 BFS），供显式要求框架级语义游走时使用。

#### Scenario: neighbors 一跳与截断

- **WHEN** 种子有 80 个去重邻居，`limit=60`
- **THEN** 渲染 MUST 恰含 60 个邻居（互斥端点在前）且标注共 80 个、提示下钻方式

#### Scenario: 载重过滤继承

- **WHEN** 对核心节点（概念 / 事实）做 neighbors associate，图中存在指向它的同 universe 事件背书边
- **THEN** 邻居 MUST NOT 含事件节点（核心侧不反查事件——载重命根）

#### Scenario: mcs 模式行为不变

- **WHEN** `associate(seed_id, mode="mcs")`
- **THEN** MUST 调 `mcs.query("", existing_context=[种子节点], universe=种子.universe)` 并经 `render_query_result` 渲染（与本 change 前行为逐字一致）

#### Scenario: hot / random 未实现

- **WHEN** `associate(seed_id, "hot")` 或 `"random"`
- **THEN** MUST 返回"未实现"提示文本（引导改用 `neighbors` 或 `mcs`）

#### Scenario: seed_id 不存在

- **WHEN** seed_id 在图中不存在
- **THEN** MUST 返回错误提示文本，MUST NOT 抛异常中断

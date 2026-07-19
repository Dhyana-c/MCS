# memory-agent Spec Delta — retire-framework-query-pipeline

## MODIFIED Requirements

### Requirement: MemoryStore 复用共享渲染纯函数

`MemoryStore` SHALL 复用核心库 `mcs.rendering` 的公开纯函数 `format_ingest_status`（`learn` 渲染）。`associate` 仅保留 **`neighbors` 模式**（默认），SHALL 用 MemoryStore 自有节点列表渲染（含 `[id:...]` 存根、name==content 只写一份口径），MUST NOT 调用任何查询管线。**`render_query_result` 不再被复用**（其唯一调用者 `associate(mode="mcs")` 已删除；`render_query_result` 本身随读查询退役而从 `mcs.rendering` 移除——见 `result-rendering` delta）。MUST NOT 引用任何应用包的内部 / 私有函数。

#### Scenario: learn 渲染复用 format_ingest_status

- **WHEN** `MemoryStore` 渲染 `learn` 结果
- **THEN** MUST 经 `format_ingest_status`（核心库公开纯函数）

#### Scenario: neighbors 模式零管线

- **WHEN** `MemoryStore.associate(seed_id)` 执行（默认 neighbors）
- **THEN** MUST NOT 调用 `mcs.query` / 查询管线，MUST NOT 产生任何 LLM 调用；渲染 MUST 含每个邻居的 `[id:...]` 存根

> 原 "Scenario: mcs 模式渲染复用" REMOVED（mode="mcs" 删除）。

---

### Requirement: associate 原语（联想扩展）

`MemoryStore.associate(seed_id)` 经 `store.get_relations(seed)` 取种子作任一端的 `关联` / `互斥` 边、渲染**一跳邻居**（纯图读、零 LLM）——相关性判断归 agent 的多轮探索（工具内 MUST NOT 嵌套 BFS / LLM 筛选）。载重双类过滤由 `get_relations` 天然继承。**互斥邻居 SHALL 单列在前**。邻居数按 `limit`（默认 60）截断，超出标注总数与下钻方式。

**`mode` 参数删除**：原 `mode="mcs"`（全管线 BFS）与 `mode="neighbors"` 二选一收敛为**仅 neighbors**——框架读查询编排已退役（见 query-pipeline delta），`mcs` 模式无底层 `mcs.query` 可调。

#### Scenario: neighbors 一跳与截断

- **WHEN** 种子有 80 个去重邻居，`limit=60`
- **THEN** 渲染 MUST 恰含 60 个邻居（互斥端点在前）且标注共 80 个、提示下钻方式

#### Scenario: 载重过滤继承

- **WHEN** 对核心节点做 neighbors associate，图中存在指向它的同 universe 事件背书边
- **THEN** 邻居 MUST NOT 含事件节点（核心侧不反查事件——载重命根）

#### Scenario: seed_id 不存在

- **WHEN** seed_id 在图中不存在
- **THEN** MUST 返回错误提示文本，MUST NOT 抛异常中断

> 原 "Scenario: mcs 模式行为不变" REMOVED。原 "Scenario: hot / random 未实现" 调整为：未实现模式仅剩历史口径，associate 不再接受 `mode` 参数（hot/random 不再暴露）。

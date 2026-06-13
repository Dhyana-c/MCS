# query-pipeline Specification

## Purpose
定义读流程为 5 段固定管线（前置插件→种子定位→语义理解 Loop→仲裁→后置处理），默认返回 List[Node]，各段独立可观察。
## Requirements
### Requirement: 读流程为 5 段固定管线

The system SHALL implement query as a 5-stage pipeline in this fixed order: ① 前置插件链 → ② 种子定位 → ③ 语义理解 Loop → ④ 仲裁 → ⑤ 后置处理链.

#### Scenario: 5 段顺序固定

- **WHEN** 调用 `QueryEngine.query(text)`
- **THEN** 框架 MUST 按 ①→②→③→④→⑤ 顺序执行；任何插件不得调整段的顺序

#### Scenario: 各段独立可观察

- **WHEN** 任一段抛出异常或被显式短路
- **THEN** 后续段 MUST 不被执行；框架 MUST 在 `QueryContext.metadata` 中标记中止位置

---

### Requirement: 阶段 ① 使用独立的 PreprocessPlugin 类型

The system SHALL modify stage ① (前置插件链) to use `PluginType.PREPROCESS` for locating plugins, instead of filtering `PostprocessPlugin` by `position` attribute.

#### Scenario: 前置插件类型独立

- **WHEN** 查询管线执行阶段 ①
- **THEN** 框架 MUST 通过 `plugin_manager.get_all(PluginType.PREPROCESS)` 获取前置插件链

#### Scenario: 前置插件处理文本

- **WHEN** 前置插件链执行
- **THEN** 每个插件的输入和输出 MUST 是 `str` 类型

---

### Requirement: query 默认返回节点集合而非答案文本

The system SHALL default `QueryEngine.query()` to return `List[Node]` (the `result_set` field of `QueryContext`). Synthesizing a natural-language answer is OPTIONAL and only happens if a `PostprocessPluginInterface` instance in stage ⑤ produces it.

#### Scenario: 未配置合成插件时返回节点集合

- **WHEN** 配置中后置处理链不含任何合成相关插件
- **THEN** `query()` 返回值的类型 MUST 是 `List[Node]`

#### Scenario: 配置合成插件时输出形态由插件决定

- **WHEN** 后置处理链最后一个插件返回 `str`
- **THEN** `query()` 返回值类型 MUST 与该插件返回值一致；MCS 框架不强制类型转换

#### Scenario: README 与文档反映"记忆系统"定位

- **WHEN** 用户查阅 `README.md` 或 capability spec 介绍段
- **THEN** 描述中 MUST 用"可扩展记忆系统"而非"问答系统"指代 MCS 默认形态

---

### Requirement: 多轮驻留节点跳过种子定位

The system SHALL accept an optional `existing_context` parameter on `query()`. When provided, stage ② (种子定位) is SKIPPED and stage ③ uses `existing_context` as the initial `frontier`.

#### Scenario: 传入 existing_context 跳过种子定位

- **WHEN** `query(text, existing_context=[nodeA, nodeB])`
- **THEN** 框架 MUST 不调用任何 EntryPlugin；③ Loop 的初始 `frontier` MUST 是 `[nodeA, nodeB]`

#### Scenario: 多轮上下文由调用方维护

- **WHEN** 调用方希望延续上一轮查询的语境
- **THEN** 调用方 MUST 自行保存上一轮的 `result_set`，并在下一轮以 `existing_context` 形式传入；MCS 框架自身不维护跨调用的会话状态

---

### Requirement: 入口插件链累积合并并按优先级排序

In stage ②, all registered `EntryPluginInterface` instances SHALL execute. Their outputs MUST be merged and sorted by plugin priority (descending). A plugin MAY declare `exclusive=True` to short-circuit lower-priority plugins on non-empty hit. Each plugin's `locate` call SHALL be independently wrapped in try/except; a single plugin failure MUST NOT prevent other plugins from executing.

#### Scenario: 多个入口插件全部执行

- **WHEN** 配置三个入口插件 A(priority=100)、B(priority=80)、C(priority=0)，A 和 B 都返回非空候选
- **THEN** 框架 MUST 把 A 和 B 的候选合并，按优先级排序后送入下一步（C 的执行取决于是否短路）

#### Scenario: exclusive 短路低优先级插件

- **WHEN** 高优先级插件 A 声明 `exclusive=True` 且返回非空候选
- **THEN** 框架 MUST 不调用比 A 优先级低的插件

#### Scenario: 全部入口插件返回空

- **WHEN** 所有入口插件（含 priority=0 的兜底）都返回空
- **THEN** 框架 MUST 返回空 `seeds`；后续 ③ Loop 立即终止；最终 `result_set` 为空

#### Scenario: 单插件异常隔离

- **WHEN** 入口插件 A（priority=100）的 `locate` 方法抛出异常
- **THEN** 框架 MUST 记录 WARNING 日志（含插件名和错误信息），继续执行后续入口插件 B/C；MUST NOT 让 A 的异常拖垮整次种子定位

#### Scenario: 所有插件异常时返回空

- **WHEN** 所有入口插件均抛出异常
- **THEN** 框架 MUST 返回空 `seeds`；后续遍历 MUST 自然终止；MUST 记录每次异常的 WARNING 日志

---

### Requirement: 顶点导航兜底作为最低优先级入口插件

The system SHALL provide a `HubFallbackEntryPlugin` with `priority=0` and `exclusive=False`. It MUST NOT be hardcoded into the query pipeline; it MUST live in the entry plugin chain like any other entry plugin.

#### Scenario: 兜底插件存在于默认配置

- **WHEN** 加载 `MCSConfig.knowledge_graph()` 默认配置
- **THEN** 入口插件链 MUST 包含一个 priority=0 的 HubFallbackEntryPlugin

#### Scenario: 用户可以替换或删除兜底

- **WHEN** 用户从配置中移除 HubFallbackEntryPlugin
- **THEN** 框架 MUST 允许该配置；并在所有其他入口插件都返回空时，最终 `seeds` 为空（不强制保留兜底）

---

### Requirement: 种子裁剪使用 TrimPlugin 链

In stage ②, after entry plugin merge, seeds MUST go through a TrimPlugin chain for reduction. The chain SHALL execute serially, each plugin's output becoming the next's input. Plugins are sorted by priority (descending). The same interface MAY be reused at stage ④ arbitration.

#### Scenario: 执行顺序为 Entry → TrimPlugin 链

- **WHEN** 查询管线执行阶段 ②
- **THEN** 执行顺序 MUST 是：EntryPlugin 链（合并）→ TrimPlugin 链（按优先级排序，依次裁剪）

#### Scenario: TrimPlugin 链可空

- **WHEN** 未配置任何 TrimPlugin
- **THEN** 框架 MUST 跳过裁剪，直接返回 EntryPlugin 合并输出

#### Scenario: 种子超 T 触发裁剪

- **WHEN** 入口插件合并产出 N 个候选节点，估算总 token > T
- **THEN** TrimPlugin 链 MUST 将候选裁剪到 ≤ T

#### Scenario: 语义 TrimPlugin 按 query 筛选

- **WHEN** 注册了 SemanticTrimPlugin（或类似实现）
- **THEN** 插件 MAY 使用 LLM 按 query 语义筛选节点（可重排）；MUST 满足预算约束

---

### Requirement: 语义理解 Loop 为 BFS 且维护 visited 集合

Stage ③ SHALL implement a breadth-first traversal. A `visited: set[node_id]` MUST be maintained throughout the loop to prevent revisits, because the concept graph allows cycles.

#### Scenario: 访问过的节点不再被处理

- **WHEN** 节点 N 已在 `visited` 集合中
- **THEN** 当 N 再次出现在 `frontier` 时，框架 MUST 跳过对 N 的邻域加载和 LLM 调用

#### Scenario: 有环图不会死循环

- **WHEN** 图中存在环 A→B→C→A，遍历从 A 开始
- **THEN** ③ Loop MUST 在有限步内终止；A、B、C 各被处理至多一次

---

### Requirement: 语义理解 Loop 的安全阀

Stage ③ SHALL enforce safety valves: `max_rounds` (BFS rounds / hops) and `max_accumulated_nodes` (hard node count limit). The loop MUST terminate when either limit is reached, regardless of LLM judgment. The primary termination condition is `token_budget.T` — when `accumulated` token sum exceeds T, the loop terminates.

#### Scenario: 达到 max_rounds 强制终止

- **WHEN** 第 `max_rounds` 轮完成，`frontier` 仍非空
- **THEN** 框架 MUST 不再启动新一轮 BFS；`accumulated` 在该时刻定型

#### Scenario: 达到 max_accumulated_nodes 强制终止

- **WHEN** `accumulated` 节点数达到 `max_accumulated_nodes`
- **THEN** 框架 MUST 立即终止 Loop（即使当前轮未完成）

#### Scenario: token 预算超限终止

- **WHEN** `accumulated` 的估算 token 总和 > `token_budget.T`
- **THEN** 遍历 MUST 立即终止

#### Scenario: LLM 自然收敛优先于硬上限

- **WHEN** 某一轮 LLM 筛选结果为空，且尚未达到任何硬上限
- **THEN** `frontier` 为空，Loop MUST 自然终止；这是自然终点

---

### Requirement: 语义理解 Loop 使用 select_nodes 筛选候选

Within stage ③, the framework MUST issue LLM calls with `purpose = select_nodes` to filter frontier nodes. The calls SHALL use batch expansion strategy: multiple frontier nodes and their neighbors can be combined into a single LLM call as long as total tokens ≤ budget.

#### Scenario: 批量扩展减少 LLM 调用次数

- **WHEN** multiple frontier nodes have neighbors that fit within token budget when combined
- **THEN** framework MUST issue ONE LLM call for the batch instead of one call per frontier node

#### Scenario: 仅选中邻居节点加入 accumulated 和 visited

- **WHEN** LLM returns selected node IDs from batch expansion
- **THEN** selected neighbor nodes MUST be added to `accumulated` and `visited`; center nodes MUST NOT be added (they are already visited); unselected neighbors MUST NOT be added to `visited`

#### Scenario: 未选中邻居可被后续轮次重新发现

- **WHEN** LLM does not select a neighbor candidate
- **THEN** that neighbor MUST NOT be added to `visited`; subsequent rounds MAY rediscover it via other paths

#### Scenario: 批量超预算时拆分或逐节点处理

- **WHEN** combined batch would exceed `token_budget.T`
- **THEN** framework MUST either split into smaller batches or fallback to single-node processing

---

### Requirement: 仲裁单一职责且每条管线至多一个

Stage ④ arbitration SHALL accept at most ONE `ArbitrationPluginInterface` instance. Its job is exactly `List[Node] -> List[Node]` — selecting the final result set from `accumulated`. The arbitration step MUST NOT change node content, MUST NOT produce non-Node outputs.

#### Scenario: 配置 0 个仲裁插件直接透传

- **WHEN** 配置中没有 ArbitrationPlugin
- **THEN** `result_set` MUST 等于 `accumulated`

#### Scenario: 配置 ≥2 个仲裁插件报错

- **WHEN** 配置中注册了 2 个或更多 ArbitrationPlugin
- **THEN** 框架 MUST 在初始化阶段抛出配置错误，提示"仲裁位至多一个"

#### Scenario: 仲裁输出仍是 List[Node]

- **WHEN** 仲裁插件返回值类型不是 `List[Node]`
- **THEN** 框架 MUST 抛出运行时错误，禁止仲裁输出形态变更

---

### Requirement: 后置处理链开放可串联

Stage ⑤ SHALL accept 0..N `PostprocessPluginInterface` instances forming a serial chain. Each plugin's output becomes the next plugin's input. The first plugin receives `selected: List[Node]`; the final plugin's output is `query()` 的返回值. Output type is unconstrained.

#### Scenario: 链中插件按注册顺序串联

- **WHEN** 后置链含 [P1, P2, P3]
- **THEN** 框架 MUST 调用 P1(selected) → P2(P1的输出) → P3(P2的输出)；返回 P3 的输出

#### Scenario: 输出形态自由

- **WHEN** 后置链含一个返回 `str` 的合成插件 + 一个返回 `dict` 的元信息插件
- **THEN** 框架 MUST 允许此链；不强制中间类型一致

#### Scenario: 空链返回原节点集

- **WHEN** 后置链为空
- **THEN** `query()` 的返回值 MUST 等于 `selected`（即 `result_set`）

---

### Requirement: QueryContext 含四个状态字段

The system SHALL provide a `QueryContext` data class threaded through the entire query call, containing exactly these 4 lifecycle fields: `system_prompt`, `user_input`, `intermediate`, `result_set`. Free `metadata` dict allowed.

#### Scenario: 字段语义对应生命周期

- **WHEN** 检查 QueryContext 字段定义
- **THEN** `system_prompt` 和 `user_input` MUST 在整次 query 调用中不变；`intermediate` MUST 在 ③ Loop 内变化（等价于 `accumulated`）；`result_set` MUST 在 ④ 仲裁完成后定型（等价于 `selected`）

#### Scenario: 插件可读 ctx 但不得越权写

- **WHEN** 后置插件试图修改 `system_prompt` 或 `user_input`
- **THEN** 框架 MUST 阻止该修改（通过文档约定或运行时保护，由 Phase 1 实现决定具体形式）


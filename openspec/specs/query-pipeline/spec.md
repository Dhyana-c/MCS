# query-pipeline Specification

## Purpose
定义读流程为 5 段固定管线（前置插件→种子定位→语义理解 Loop→仲裁→后置处理），默认返回 Subgraph，各段独立可观察。
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

### Requirement: query 默认返回 Subgraph

`QueryEngine.query()` SHALL 默认返回 `Subgraph`（`nodes` + `edges`）。`edges` MUST 仅含被选中的关系边（`关联` / `互斥`），MUST NOT 含由聚类涌现的层级（组织）边，MUST NOT 按 `relation_model` 分模式。期望 `List[Node]` 的后置插件 MUST 经兼容层接收 `subgraph.nodes`。

#### Scenario: 返回 Subgraph

- **WHEN** 后置处理链为空
- **THEN** `query()` MUST 返回 `Subgraph`，`nodes` 为累积节点，`edges` 为选中的 `关联` / `互斥` 边

#### Scenario: edges 不含层级（组织）边

- **WHEN** 检查返回的 `Subgraph.edges`
- **THEN** MUST 仅含 `关联` / `互斥` 边，MUST NOT 含聚类形成的"组织中心 → 成员"层级边

#### Scenario: 后置插件兼容 List[Node]

- **WHEN** 后置链含期望 `List[Node]` 的旧插件
- **THEN** 框架 MUST 从 `Subgraph.nodes` 提取节点列表传入

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

### Requirement: 入口为字面 foothold + 反查 + 多种

种子定位（阶段 ②）MUST 以**字面实体链接**为主力：用 jieba 切词，将 query token 匹配概念名 / 别名得到 foothold 概念。embedding MUST 仅在"query 中无任何有名实体命中"时作兜底；`__seed_root__` 下钻 MUST 仅作孤儿 / 最后退路，MUST NOT 作主入口。入口 MUST 只需取得"一个 foothold"即可——经反查与多种子扩散补全。

#### Scenario: jieba 字面命中实体

- **WHEN** query 含图中某概念的名 / 别名
- **THEN** 系统 MUST 经 jieba 切词 + 字面匹配将其定位为 foothold 种子

#### Scenario: embedding 仅兜底

- **WHEN** query 中无任何有名实体可字面命中
- **THEN** 系统 MAY 用 embedding 兜底；其余情形 MUST NOT 依赖 embedding 作主力

#### Scenario: 单 foothold 经反查补全

- **WHEN** 仅命中一条相关事实的一端 A（另一端 B 未直接命中）
- **THEN** 反查 MUST 把 B 与该事实一并拉入，无需两端都被选中

---

### Requirement: 短边优先选事实

累积结果时，框架 SHALL **优先就近事实**（更短路径）。hub 在其所在层级 MUST 仍作为可见邻居呈现（不因走短边而丢失 gist 概念）。

#### Scenario: 就近事实优先

- **WHEN** 目标既可经直接事实到达、也可经更长路径到达
- **THEN** 框架 SHOULD 优先采纳更短的那条；长度仅作就近偏好，MUST NOT 据此删除携带不同语义的平行事实

---

### Requirement: entity-anchored 检索，否定由 LLM 现推

检索 MUST 以**实体为锚**——找出该实体经 `关联` 连到的**命题节点**，MUST NOT 按 query 中的谓词过滤。否定 / 极性问题 MUST 由 LLM 在检索回的命题上现推，MUST NOT 以"命题缺失"作否定依据（开放世界，缺命题 ≠ 否定）。

#### Scenario: 极性问题靠矛盾命题

- **WHEN** 问"小明是否讨厌苹果"，图中有命题"小明喜欢苹果"经关联连小明与苹果、无"讨厌"命题
- **THEN** 框架 MUST 检索到"喜欢"命题，由 LLM 据"喜欢 ⊥ 讨厌"答"不讨厌"；MUST NOT 因"无讨厌命题"直接下结论

#### Scenario: 不按谓词过滤

- **WHEN** query 谓词在图中无对应命题
- **THEN** 检索 MUST 仍返回相关实体间的命题（让 LLM 判读），MUST NOT 返回空

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

### Requirement: 语义理解 Loop 使用 select_facts 筛选候选

阶段 ③ MUST 以**核心 BFS** 进行：每访问一个节点，渲染其**活跃双向视图**（{该节点的 `关联` 邻居（命题 / 概念，两端可达、反查）+ 层级邻居}），以可配置的 `select_purpose` 让 LLM 选相关命题 / 邻居。`_traverse` MUST 接受参数 `select_purpose: str`，**默认 `"select_facts"`**；读路径 `query()` MUST 使用默认值（即宽召回 `select_facts`）。视图收敛：**Phase 2** 按 `priority` 截断 ≤ T；**Phase 1 不截断**。遍历 MUST 按层级分批（不变量保证每层 ≤ T）。**事件默认不进视图**（核心不反查事件），需出处时走按需 `事实 → 事件` 定向查。

读侧 `select_facts` 的 LLM 输出 MUST 为**双角色**：每个选中条目标注为 `结果`（进 `accumulated`）/ `探索`（进 `frontier`）/ 两者。`_consume` MUST 按角色分流：`结果`（含两者）→ `accumulated`（吃 T、计 `used_tokens`）+ `visited`；`探索`（含两者）→ 下一轮 `frontier`（不吃 T）+ `visited`。被任一角色选中者 MUST 入 `visited`；未被任何角色选中者 MUST NOT 入 `visited`（可后续重新发现）。选中事实边时端点归属 MUST 随该边角色。

#### Scenario: 每节点渲染活跃双向视图

- **WHEN** BFS 访问节点 A
- **THEN** 框架 MUST 渲染 A 的 `关联` 邻居（命题 / 概念）+ 层级邻居供选择，MUST NOT 默认带入连向 A 的事件

#### Scenario: 读路径使用默认 select_facts

- **WHEN** `query()` 进入阶段③ 的事实筛选
- **THEN** 框架 MUST 以 `purpose="select_facts"`（宽召回）调用 LLM；MUST NOT 因调用方不同而改变读侧 purpose

#### Scenario: 筛选 purpose 可由调用方指定

- **WHEN** `_traverse` 被调用且传入 `select_purpose="X"`
- **THEN** 阶段③ 的所有事实筛选 LLM 调用 MUST 使用 `purpose="X"`，MUST NOT 硬编码为 `select_facts`

#### Scenario: 按层分批、富余合并

- **WHEN** 多个待扩展节点的层级包合计 ≤ 预算
- **THEN** 框架 MUST 合并为一次 LLM 调用；超预算则按层切分

#### Scenario: 双角色路由

- **WHEN** `select_facts` 返回某条目标注 `结果`
- **THEN** 框架 MUST 把该条目（或事实边端点）加入 `accumulated` 并增量计入 `used_tokens`

- **WHEN** `select_facts` 返回某条目标注 `探索`（且未标注 `结果`）
- **THEN** 框架 MUST 把该条目加入下一轮 `frontier`，MUST NOT 加入 `accumulated`，MUST NOT 计入 `used_tokens`

#### Scenario: 选中补入端点

- **WHEN** LLM 选中一条命题 / 关联而其端点未被直接选中
- **THEN** 框架 MUST 把端点按该条目的角色补入（`结果` → `accumulated`；`探索` → `frontier`）

#### Scenario: 未选中邻居可被后续轮次重新发现

- **WHEN** LLM 未选中某候选
- **THEN** 该候选 MUST NOT 被加入 `visited`；后续轮次 MAY 经其他路径重新发现

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

### Requirement: select_facts 采用宽召回口径

读路径阶段 ③ 的事实筛选（`purpose=select_facts`）SHALL 在**探索维度**（`探索` 角色，进 `frontier`）采用**宽召回**口径：只要候选事实条目涉及查询中的任何实体、主题、时间、比较对象或其关联事实，就应纳入探索，宁可多召回交由后续收敛，MUST NOT 因"没有哪一条直接回答了查询"而漏选探索或返回空。

进 LLM 的**结果维度**（`结果` 角色，进 `accumulated`）SHALL 采用**精筛**口径：只要条目对回答有贡献就标 `结果`，仅当条目**明显只是路径跳板、自身不含答案信息**（如纯组织 hub / 中转概念）才单标 `探索`。候选事实条目不少于 5 条时，`结果` SHALL 至少返回 3 条最相关的（防 comparison 空返回）。

默认 `select_facts` prompt bundle（`mcs.prompts.select_facts.SYSTEM_PROMPT` / `USER_TEMPLATE`）MUST 同时体现上述探索宽召回与结果精筛两维口径。

噪声收敛分三层：**探索层宽召回（不压制）→ `结果` 标签同调精筛（控进 LLM / T 边界，框架层）→ 下游 rerank / 裁剪收敛最终排序（结果层）**。

> 注：本口径**仅约束读路径**。写管线阶段 ② 关联定位使用独立的窄召回 `select_facts_write`（见 `read-write-select-prompt-split`），不受本口径约束；其 flat-array 输出由 `parse` 归一为"两者"，写路径行为不变。

#### Scenario: 探索维度宽召回宁可多选

- **WHEN** 候选中存在与查询实体 / 主题 / 时间 / 比较对象相关的条目，但无任一条直接回答查询
- **THEN** `select_facts` MUST 仍把这些相关条目标注 `探索`（进 frontier），MUST NOT 返回空

#### Scenario: 结果维度精筛剔除纯跳板

- **WHEN** 某条目仅为组织 hub / 中转概念、自身不含答案信息
- **THEN** `select_facts` SHOULD 单标 `探索`（不进 accumulated）；对回答有贡献的条目 MUST 标 `结果`

#### Scenario: 候选充足时结果下限返回

- **WHEN** 候选事实条目不少于 5 条且存在相关项
- **THEN** `select_facts` 的 `结果` 维度 SHALL 至少返回 3 条最相关条目

#### Scenario: 默认 prompt 体现双维口径

- **WHEN** 导入 `mcs.prompts.DEFAULT_PROMPTS["select_facts"]`
- **THEN** 其 system / template MUST 体现"探索宽召回 + 结果精筛"双维，MUST NOT 退化为单维宽召回或单维窄召回

### Requirement: frontier 与 accumulated 解耦

阶段 ③ 的 `frontier`（BFS 待扩展队列）与 `accumulated`（进 LLM 的输出集）SHALL 成员解耦——二者由 `select_facts` 同一次调用的角色标签分别填充，成员**可以不同**。`frontier` MUST 仅存引用、不进 LLM、不计入 `token_budget`；`accumulated` MUST 进 LLM、计入 `token_budget`（`≤ T`）、且为 `_traverse` 的返回集。`_traverse` MUST 在遍历结束时丢弃 `frontier`，MUST NOT 把 `frontier` 作为结果返回。

#### Scenario: frontier 不进结果

- **WHEN** 某节点仅被标 `探索`（进 frontier、未进 accumulated）
- **THEN** `_traverse` 的返回集 MUST NOT 含该节点（除非它在后续轮次被标 `结果`）

#### Scenario: accumulated 为返回集

- **WHEN** `_traverse` 结束
- **THEN** 返回的节点集 MUST 等于 `accumulated`，MUST NOT 等于 `frontier` 或二者并集

#### Scenario: frontier 不吃 T

- **WHEN** 节点进入 `frontier`（仅 `探索`）
- **THEN** `used_tokens` MUST NOT 因此增加；该节点 token MUST NOT 计入 `accumulated ≤ T` 的判断


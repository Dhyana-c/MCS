# lightweight-query Specification

## Purpose

提供轻量查询模式，供写入管线阶段②快速定位关联节点。跳过仲裁和后置处理阶段，减少不必要的 LLM 调用开销，同时消除 isinstance 静默降级逻辑。
## Requirements
### Requirement: QueryEngine 提供 query_nodes 轻量查询方法

`QueryEngine` SHALL 提供 `query_nodes(text: str, max_rounds: int = 1, universe: str | None = None) -> List[Node]` 方法，**专供写管线阶段②关联定位使用**。执行精简遍历：种子定位（ENTRY+TRIM 链）→ ③ 遍历（限制 `max_rounds` 轮、`select_purpose="select_facts_write"`）→ 直接返回 `ctx.intermediate`。**MUST NOT 有 ④ 仲裁 / ⑤ 后处理分支**（`skip_postprocess` 参数删除——读查询编排已退役，无 ④⑤ 可跳）。**MUST NOT 经任何前置插件类型**——`QUERY_PREPROCESS` 已随读查询编排退役删除、`PluginType` 无此类型，`query_nodes` / `locate_seeds` SHALL 直接把原文传给 `_locate_seeds`（无 `_run_preprocess` 中间步骤）。

#### Scenario: 默认返回 List[Node]

- **WHEN** 调用 `query_nodes("some text")`
- **THEN** 返回值类型 MUST 为 `List[Node]`（`ctx.intermediate`），MUST NOT 经任何 PostprocessPlugin

#### Scenario: max_rounds 限制遍历深度

- **WHEN** 调用 `query_nodes("text", max_rounds=1)`
- **THEN** 遍历阶段 MUST 在 1 轮后终止，无论 frontier 是否非空

#### Scenario: 返回 List[Node] 不经 isinstance 检查

- **WHEN** `query_nodes` 返回结果
- **THEN** 返回值 MUST 为 `ctx.intermediate`（`List[Node]`），MUST NOT 做 `isinstance(related, list) else []` 转换

#### Scenario: 不经前置插件链

- **WHEN** 检查 `QueryEngine` 源码
- **THEN** MUST NOT 含 `_run_preprocess` 方法 / MUST NOT 引用任何前置插件类型（`QUERY_PREPROCESS`）
- **AND** `query_nodes` / `locate_seeds` MUST 直接把原文传给 `_locate_seeds`（无中间 no-op 步骤）

---

### Requirement: WritePipeline 阶段②使用 query_nodes

`WritePipeline` 阶段② SHALL 调用 `self.query_engine.query_nodes(processed)` 替代 `self.query_engine.query(processed)`。`ctx.related` SHALL 直接赋值为返回值，MUST NOT 包含 `isinstance(related, list) else []` 的静默降级逻辑。

#### Scenario: 阶段②调用 query_nodes

- **WHEN** WritePipeline 执行阶段②
- **THEN** MUST 调用 `query_engine.query_nodes(processed_text)`；MUST NOT 调用 `query_engine.query(processed_text)`

#### Scenario: related 直接赋值

- **WHEN** `query_nodes` 返回结果 R
- **THEN** `ctx.related` MUST 直接等于 R；MUST NOT 包含 `if isinstance(R, list) else []` 逻辑

#### Scenario: 空结果不阻塞写入

- **WHEN** `query_nodes` 返回空列表
- **THEN** `ctx.related` MUST 为空列表；框架 MUST 继续执行 ③（与现有行为一致）

---

### Requirement: 写管线关联定位使用窄召回 select_facts_write

`query_nodes()` 在遍历阶段 SHALL 以 `select_purpose="select_facts_write"` 调用 `_traverse`，使写侧事实筛选使用**窄召回**口径。框架 SHALL 在 `mcs.prompts.DEFAULT_PROMPTS` 注册默认 `select_facts_write` bundle（窄召回：选最相关、优先具体信息、可返回空），其 `parse` 与原 `select_facts` 等价。

> **MODIFIED 要点**：原条目"与读侧 `query()` 的宽召回 `select_facts` 解耦"措辞删除——读侧 `select_facts` bundle 随 `query()` 退役而删除（见 query-pipeline delta #17）。本 requirement 现为**唯一存活**的事实筛选 purpose。

#### Scenario: query_nodes 走 select_facts_write

- **WHEN** `query_nodes("text")` 进入遍历阶段的事实筛选
- **THEN** 框架 MUST 以 `purpose="select_facts_write"` 调用 LLM

#### Scenario: 默认注册 select_facts_write

- **WHEN** 导入 `mcs.prompts.DEFAULT_PROMPTS`
- **THEN** MUST 含 `select_facts_write` 条目；MUST NOT 含已退役的读侧 `select_facts` 条目

#### Scenario: 空结果不阻塞写入

- **WHEN** 窄召回下 `query_nodes` 返回空列表
- **THEN** `ctx.related` MUST 为空列表；框架 MUST 继续执行写管线阶段③

### Requirement: locate_seeds 入口为字面 foothold + 反查 + 多种

`QueryEngine.locate_seeds(query, universe)`（供 agent `search` 与写管线 `query_nodes` 经 `_locate_seeds` 复用）MUST 以**字面实体链接**为主力：jieba 切词匹配概念名 / 别名得 foothold。embedding 仅在"query 无任何有名实体命中"时兜底；`__seed_root__` 下钻仅作孤儿 / 最后退路。入口只需"一个 foothold"——经反查与多种子扩散补全。

#### Scenario: jieba 字面命中实体

- **WHEN** query 含图中某概念的名 / 别名
- **THEN** 系统 MUST 经 jieba 切词 + 字面匹配定位为 foothold 种子

#### Scenario: 单 foothold 经反查补全

- **WHEN** 仅命中一条相关事实的一端 A
- **THEN** 反查 MUST 把另一端 B 与该事实一并拉入

---

### Requirement: locate_seeds 经 ENTRY 插件链累积合并并按优先级排序

`_locate_seeds` 中所有注册的 `EntryPluginInterface` 实例 SHALL 全部执行，输出合并并按 plugin priority 降序排序。插件 MAY 声明 `exclusive=True` 在非空命中时短路低优先级插件。每个 `locate` 调用独立 try/except，单插件失败 MUST NOT 阻止其他插件。

#### Scenario: exclusive 短路低优先级插件

- **WHEN** 高优先级插件 A 声明 `exclusive=True` 且返回非空
- **THEN** MUST 不调用比 A 优先级低的插件

#### Scenario: 单插件异常隔离

- **WHEN** 入口插件 A 的 `locate` 抛异常
- **THEN** MUST 记 WARNING 并继续执行后续插件 B/C

---

### Requirement: HubFallbackEntryPlugin 作为最低优先级入口插件

系统 SHALL 提供 `HubFallbackEntryPlugin`（priority=0、exclusive=False），MUST NOT 硬编码进 locate_seeds，MUST 经 entry 插件链参与。

#### Scenario: 兜底插件存在于默认配置

- **WHEN** 加载 `MCSConfig.knowledge_graph()` 默认配置
- **THEN** 入口插件链 MUST 含 priority=0 的 HubFallbackEntryPlugin

---

### Requirement: 种子裁剪使用 TrimPlugin 链

ENTRY 合并后，seeds MUST 经 TrimPlugin 链逐个裁剪（按 priority 降序串行）。未配置 TrimPlugin 时跳过裁剪。

#### Scenario: TrimPlugin 链可空

- **WHEN** 未配置任何 TrimPlugin
- **THEN** MUST 跳过裁剪，直接返回 ENTRY 合并输出

#### Scenario: 语义 TrimPlugin 按 query 筛选

- **WHEN** 注册了 SemanticTrimPlugin
- **THEN** 插件 MAY 用 LLM 按 query 语义筛选 / 重排；MUST 满足预算约束

---

### Requirement: `_traverse` 为 BFS 且维护 visited 集合

`QueryEngine._traverse`（供 `query_nodes` 调用）SHALL 实现广度优先遍历。全程维护 `visited: set[node_id]` 防止 revisit（概念图允许环）。

#### Scenario: 访问过的节点不再被处理

- **WHEN** 节点 N 已在 `visited`
- **THEN** N 再次出现在 frontier 时 MUST 跳过其邻域加载与 LLM 调用

#### Scenario: 有环图不会死循环

- **WHEN** 图中存在环 A→B→C→A
- **THEN** Loop MUST 在有限步内终止；A/B/C 各处理至多一次

---

### Requirement: `_traverse` 的安全阀

`_traverse` SHALL 强制 `max_rounds`（BFS 轮数）与 `max_accumulated_nodes`（硬节点数上限）与 `max_frontier_nodes`（frontier 宽度阀）。达任一上限 MUST 终止。主终止条件为 `token_budget.T`——`accumulated` token 超 T 即终止。

#### Scenario: 达到 max_rounds 强制终止

- **WHEN** 第 `max_rounds` 轮完成且 frontier 仍非空
- **THEN** MUST 不再启动新一轮；`accumulated` 定型

#### Scenario: token 预算超限终止

- **WHEN** `accumulated` 估算 token 总和 > `token_budget.T`
- **THEN** 遍历 MUST 立即终止

---

### Requirement: `_traverse` 使用 select_facts_write 筛选候选

`_traverse` 每访问一节点，渲染其**活跃双向视图**（`关联` 邻居 + 层级邻居），以 `select_purpose` 让 LLM 选相关命题 / 邻居。`select_purpose` 默认值 MUST 为 `"select_facts_write"`（唯一存活 bundle——读侧 `select_facts` bundle 已随 retire-framework-query-pipeline 退役删除、`DEFAULT_PROMPTS` 无 `select_facts` 键）；写路径（`query_nodes`）显式传 `"select_facts_write"`。默认值 MUST 在 `DEFAULT_PROMPTS` 命中、MUST NOT 指向不存在的 bundle（防 latent `KeyError`）。视图渲染、双角色（结果/探索）分流、端点补入、按层分批规则沿用既有语义。

#### Scenario: 每节点渲染活跃双向视图

- **WHEN** BFS 访问节点 A
- **THEN** MUST 渲染 A 的 `关联` 邻居 + 层级邻居供选择，MUST NOT 默认带入连向 A 的事件

#### Scenario: select_purpose 可由调用方指定

- **WHEN** `_traverse` 被调用且传入 `select_purpose="X"`
- **THEN** 该次遍历的事实筛选 LLM 调用 MUST 用 `purpose="X"`

#### Scenario: 默认 select_purpose 命中存活 bundle

- **WHEN** `_traverse` 被调用且未传 `select_purpose`
- **THEN** MUST 以默认值 `"select_facts_write"` 调 LLM
- **AND** 该 purpose MUST 在 `DEFAULT_PROMPTS` 命中（MUST NOT 抛 `KeyError('No prompt bundle registered for purpose=select_facts')`）

### Requirement: frontier 与 accumulated 解耦

`_traverse` 的 `frontier`（待扩展队列）与 `accumulated`（进 LLM 输出集）SHALL 成员解耦——由 `select_facts` 同一次调用的角色标签分别填充，成员可以不同。`frontier` 仅存引用、不进 LLM、不计 `token_budget`；`accumulated` 进 LLM、计入 `token_budget`（≤ T）、为 `_traverse` 返回集。遍历结束 MUST 丢弃 frontier。

#### Scenario: accumulated 为返回集

- **WHEN** `_traverse` 结束
- **THEN** 返回集 MUST 等于 `accumulated`，MUST NOT 含仅 `探索` 的节点

#### Scenario: frontier 不吃 T

- **WHEN** 节点仅进 `frontier`
- **THEN** `used_tokens` MUST NOT 因此增加

---

### Requirement: QueryContext 为导航 / 遍历的轻量上下文

`QueryEngine` SHALL 提供 `QueryContext` dataclass，贯穿 `query_nodes` / `locate_seeds` / `_traverse` 调用，含字段：`system_prompt`、`user_input`、`universe`、`metadata`（自由 dict）。**MUST NOT 含** query 编排专属的 `intermediate` / `result_set` / `selected_edges` 生命周期字段（随 `query()` 退役删除）；`accumulated` / `visited` / `frontier` 为 `_traverse` 内部局部状态、非 QueryContext 字段。ENTRY / TRIM 插件经 `ctx` 参数读取 `user_input` / `universe`。

#### Scenario: 字段瘦身

- **WHEN** 检查 `QueryContext` 字段定义
- **THEN** MUST 含 `system_prompt` / `user_input` / `universe` / `metadata`；MUST NOT 含 `intermediate` / `result_set` / `selected_edges`

#### Scenario: ENTRY/TRIM 插件经 ctx 读取导航语境

- **WHEN** `_locate_seeds` 调用 EntryPlugin.locate / TrimPlugin.trim
- **THEN** MUST 传入 `QueryContext`（至少含 `user_input` 与 `universe`）


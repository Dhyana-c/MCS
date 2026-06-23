## MODIFIED Requirements

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

## ADDED Requirements

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

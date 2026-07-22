# lightweight-query Delta

> migration-audit-fixes：C1 `_traverse` 默认 `select_purpose` 从已删的 `select_facts` 改为唯一存活的
> `select_facts_write`（掐灭 latent KeyError）；C3 删 `QueryEngine._run_preprocess` 死壳（QUERY_PREPROCESS
> 已退役、方法恒 return text）。

## MODIFIED Requirements

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

# lightweight-query Specification

## Purpose

提供轻量查询模式，供写入管线阶段②快速定位关联节点。跳过仲裁和后置处理阶段，减少不必要的 LLM 调用开销，同时消除 isinstance 静默降级逻辑。

## Requirements

### Requirement: QueryEngine 提供 query_nodes 轻量查询方法

`QueryEngine` SHALL 提供 `query_nodes(text: str, max_rounds: int = 1, skip_postprocess: bool = True) -> List[Node]` 方法。该方法执行精简的查询管线：① 前置插件链 → ② 种子定位 → ③ 遍历（限制 max_rounds 轮）→ 直接返回 `ctx.result_set`，跳过 ④ 仲裁和 ⑤ 后置处理链。

#### Scenario: 默认参数跳过后处理

- **WHEN** 调用 `query_nodes("some text")`
- **THEN** MUST 跳过仲裁（④）和后置处理链（⑤）；返回值类型 MUST 为 `List[Node]`

#### Scenario: max_rounds 限制遍历深度

- **WHEN** 调用 `query_nodes("text", max_rounds=1)`
- **THEN** 遍历阶段 MUST 在 1 轮后终止，无论是否还有未探索的 frontier 节点

#### Scenario: skip_postprocess=False 时执行后处理

- **WHEN** 调用 `query_nodes("text", skip_postprocess=False)`
- **THEN** MUST 执行完整的 ④⑤ 阶段

#### Scenario: 返回 List[Node] 不经 isinstance 检查

- **WHEN** `query_nodes` 返回结果
- **THEN** 返回值 MUST 为 `ctx.result_set`（`List[Node]`），MUST NOT 对返回值做 `isinstance(related, list) else []` 转换

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

`query_nodes()`（供写管线阶段②关联节点定位复用）在执行遍历阶段时 SHALL 以 `select_purpose="select_facts_write"` 调用 `_traverse`，使写侧事实筛选使用**窄召回**口径，与读侧 `query()` 的宽召回 `select_facts` 解耦。框架 SHALL 在 `mcs.prompts.DEFAULT_PROMPTS` 注册默认 `select_facts_write` bundle（窄召回：选最相关、优先具体信息、可返回空），其 `parse` 与 `select_facts` 等价（同为编号 JSON 数组解析）。

写侧窄召回的目的：阶段② 产出的关联节点喂给 `extract_concepts` / `judge_relations` 做"已有节点对齐"（合并同义、判互斥），需高精度——宽召回会拉入弱相关节点、抬高错并 / 错判互斥率、污染图结构。

#### Scenario: query_nodes 走 select_facts_write

- **WHEN** `query_nodes("text")` 进入遍历阶段的事实筛选
- **THEN** 框架 MUST 以 `purpose="select_facts_write"` 调用 LLM；MUST NOT 使用读侧的 `select_facts`

#### Scenario: 默认注册 select_facts_write

- **WHEN** 导入 `mcs.prompts.DEFAULT_PROMPTS`
- **THEN** MUST 含 `select_facts_write` 条目；其 `parse` MUST 与 `select_facts` 的 `parse` 行为一致（同样解析编号 JSON 数组、同样抛 `LLMParseError`）

#### Scenario: 读写 purpose 各自独立可覆盖

- **WHEN** 用户经 `MCSConfig.prompt_overrides` 覆盖 `select_facts`（或 `select_facts_write`）其中之一
- **THEN** 另一个 purpose MUST 不受影响（读写 prompt 正交）

#### Scenario: 空结果不阻塞写入

- **WHEN** 窄召回下 `query_nodes` 返回空列表
- **THEN** `ctx.related` MUST 为空列表；框架 MUST 继续执行写管线阶段③（与现有行为一致）

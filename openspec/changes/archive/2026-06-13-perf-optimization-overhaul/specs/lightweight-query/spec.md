## ADDED Requirements

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

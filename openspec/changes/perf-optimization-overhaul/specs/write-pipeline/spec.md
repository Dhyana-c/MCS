## MODIFIED Requirements

### Requirement: 关联节点定位通过轻量查询模式实现

Stage ② SHALL invoke `QueryEngine.query_nodes(processed_text)` (lightweight mode) instead of `QueryEngine.query(processed_text)`. The returned `List[Node]` becomes `WriteContext.related` and feeds stages ③④. The framework MUST NOT contain `isinstance(related, list) else []` silent degradation logic.

#### Scenario: 写入使用轻量查询模式

- **WHEN** 执行 ②
- **THEN** 框架 MUST 调用 `QueryEngine.query_nodes(processed_text)` 或等价内部方法；MUST NOT 调用 `QueryEngine.query(processed_text)`

#### Scenario: 关联定位失败不阻塞写入

- **WHEN** ② 返回空 `related`（图中暂无相关节点，如全新疆域）
- **THEN** 框架 MUST 继续执行 ③；③ 在没有 `related` 参考时 LLM 仍可基于纯 `text` 抽概念

#### Scenario: 关联定位的 LLM 调用计入预算

- **WHEN** ② 内部调用的轻量查询触发了遍历
- **THEN** 框架 MUST 把这些 LLM 调用计入本次 ingest 的总调用计数（用于监控/限流）

#### Scenario: 返回值直接赋给 related

- **WHEN** `query_nodes` 返回结果 R
- **THEN** `ctx.related` MUST 直接等于 R；MUST NOT 包含 `isinstance(R, list) else []` 转换逻辑

## ADDED Requirements

### Requirement: 定向查事件按 universe 过滤

`StoreInterface` SHALL 提供 `get_related_events(node_id, universe=None, limit=None) -> list[Node]`——绕过载重规则、返回背书此核心节点的**同 `universe`** 事件（时间倒排 + `limit` 截断）。`universe` 参数过滤：仅返回与 `node` 同 `universe` 的事件，MUST NOT 把跨 universe 事件（如作品 universe 事件被 `"__reality__"` 查询卷入）返回——避免作品纪年（非 ISO）经 ISO 排序坏掉。时间倒排仅在 `universe="__reality__"` 内保证（ISO 可比）；作品 universe 的事件排序由叙事时间线视图（`unified-graph-schema`）负责。`event_sort_key` 对非 ISO timestamp（作品纪年）MUST 容错（解析失败 fallback、不抛）。`InMemoryStore` 与 `SQLiteStore` 双实现 MUST 一致。

#### Scenario: get_related_events 按 universe 过滤

- **WHEN** 核心节点连着 `"__reality__"` 事件与作品 universe 事件（跨 universe 背书）
- **THEN** `get_related_events(核心节点, universe="__reality__")` MUST 只返回 `"__reality__"` 事件
- **AND** MUST NOT 返回作品 universe 事件

#### Scenario: 非 ISO timestamp 容错

- **WHEN** 事件 timestamp 为作品纪年（非 ISO，如"200 年"）
- **THEN** `event_sort_key` MUST 容错（不抛）
- **AND** 时间倒排仅在 `"__reality__"` 内保证

#### Scenario: 双实现一致

- **WHEN** 同一图分别用 `InMemoryStore` 与 `SQLiteStore`
- **THEN** `get_related_events`（同 `universe`）返回结果 MUST 一致

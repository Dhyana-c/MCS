## ADDED Requirements

### Requirement: 定向查事件按 universe 过滤

`StoreInterface` SHALL 提供 `get_related_events(node_id, universe=None, limit=None) -> list[Node]`——绕过载重规则、返回背书此核心节点的事件（时间倒排 + `limit` 截断）。**`universe` 参数过滤按参数分流，MUST NOT 改既有默认语义**：

- **`universe=None`（默认）返回全部背书事件（含跨 universe）**——`multi-universe-graph` 已实现并测试锁定"`get_related_events(作品 fact)` 无参跨 universe 亦返（查出处：该 fact 经哪次现实摄入进来）"。本 change MUST 保持此默认（`None` 全返），MUST NOT 改成"从节点继承 universe"——否则砍掉作品 fact 出处查询、并破坏 `multi-universe-graph` 的跨 universe 背书亦返测试。
- **传 `universe=U` 时才只返 `node.universe==U` 的事件**——叙事时间线（作品 universe）MUST 显式传 `universe=work_id`，避免作品纪年（非 ISO）经 ISO 排序坏掉。

时间倒排仅在 `universe="__reality__"` 内保证（ISO 可比）；作品 universe 的事件排序由叙事时间线视图（`unified-graph-schema`）负责。`event_sort_key` 对非 ISO timestamp（作品纪年）现状已垫底容错（不抛）；本 change 加**数字年最小解析**使纯数字纪年可排，混合 / 非数字纪年（"建安五年"）需 Phase 2 归一化。`InMemoryStore` 与 `SQLiteStore` 双实现 MUST 一致。

#### Scenario: 无参全返、跨 universe 背书亦返（兼容 mug 锁定语义）

- **WHEN** 作品 fact（`universe=<work_id>`）有现实摄入背书事件（`universe="__reality__"`），调 `get_related_events(作品 fact)`（无 `universe` 参数）
- **THEN** MUST 返回该现实摄入背书事件（跨 universe 亦返，查出处）
- **AND** MUST NOT 破坏 `multi-universe-graph` 的跨 universe 背书亦返测试

#### Scenario: 传 universe 才按 universe 过滤

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

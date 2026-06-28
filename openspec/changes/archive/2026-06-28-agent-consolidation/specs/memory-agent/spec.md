## ADDED Requirements

### Requirement: MemoryStore 结构化 ingest 原语

`MemoryStore` SHALL 提供 `ingest_structured(content: str, timestamp: str) -> str`：在单 worker 线程（`_submit`）内执行 `wctx = self._mcs.ingest(IngestInput(content=content, timestamp=timestamp))`，返回 `wctx.event_node.id`。该原语用于整合管线把精炼条目逐条入图，事件时间忠实落 `event_meta.timestamp`。调用方线程 MUST NOT 直接触碰 MCS。

> 偏离历史：旧 `personal-memory-system` 设计靠子类化 `MemStore(MemoryStore)` 规避改 `mcs_agent`；现架构"走 agent"，直接在 `MemoryStore` 上新增此原语，无需子类。原有 `learn(text: str)`（只收 str、时间盖 now）保留不变。

#### Scenario: 结构化 ingest 落事件时间

- **WHEN** 调用 `ingest_structured("今天和团队讨论了新方案", "2026-06-27T14:30:00")`
- **THEN** MUST 在 worker 线程内 `mcs.ingest(IngestInput(content=..., timestamp="2026-06-27T14:30:00"))`
- **AND** 返回的事件节点 `event_meta.timestamp` MUST 为 `2026-06-27T14:30:00`（非调用时刻）
- **AND** MUST 返回该事件节点 id

#### Scenario: 经单 worker 线程

- **WHEN** 与其他 MemoryStore 原语（learn / recall 等）并发调用 `ingest_structured`
- **THEN** MUST 经同一 `ThreadPoolExecutor(max_workers=1)` 串行执行

#### Scenario: 不改 learn 既有契约

- **WHEN** 调用既有 `learn(text)`
- **THEN** 行为 MUST 不变（内部 `mcs.ingest(text)`、时间取 now）

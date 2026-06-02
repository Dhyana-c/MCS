## ADDED Requirements

### Requirement: 持久化必须保真 round-trip

Persisted node extension data SHALL survive a save→load round-trip in a directly usable form (typed/dict), not as stringified reprs.

#### Scenario: 扩展数据 round-trip 后可用

- **WHEN** 一个带 `source_tracking`（含 `Source` 记录）的节点被 `save_node` 落盘，随后由 `load()` 读回
- **THEN** 读回节点的 `extensions["source_tracking"]["sources"]` MUST 是结构化记录（dict/Source），消费方 MUST 能直接取到 `doc_id` 等字段（MUST NOT 是 `"Source(...)"` 字符串）

#### Scenario: 向后兼容历史字符串格式

- **WHEN** `load()` 遇到历史 db 中以字符串化 `Source(...)` 形式存储的来源
- **THEN** 框架 MUST 容忍并正确还原其字段（如解析出 `doc_id`），使既有 db 无需重建即可复用

---

### Requirement: 持久化变更必须提交且可被独立读取

Each ingest's persisted nodes/edges SHALL be committed promptly, so an independent reader sees them and no in-flight data is lost on shutdown.

#### Scenario: 每次 ingest 后提交

- **WHEN** 一次 ingest 的阶段 ⑦ 落盘了 `ctx.changed` 的节点与边
- **THEN** 框架 MUST 在该次落盘后提交（commit），使另一个独立连接能读到这些节点/边

#### Scenario: shutdown 不丢最后一块

- **WHEN** 连续多次 ingest 后正常 shutdown
- **THEN** 所有已成功 ingest 的块对应的节点 MUST 已提交持久化（MUST NOT 丢失最后一次 ingest 的变更）

---

### Requirement: 续跑无空洞（幂等标记与落盘一致）

The idempotency marker for a chunk SHALL be written only after that chunk's nodes are successfully persisted, so resume never skips a chunk whose nodes were not stored.

#### Scenario: 成功后才标记已摄入

- **WHEN** 一个 `(doc_id, chunk_id)` 块走完写入管线并成功落盘
- **THEN** 框架 MUST 此时才把该块记入 `document_chunks`（去重检查仍可在前置阶段读取该表）

#### Scenario: 出错的块续跑会重试

- **WHEN** 某块在落盘前因异常中断（未成功持久化其节点）
- **THEN** 该块 MUST NOT 被标记为已摄入；续跑时框架 MUST 重新摄入该块（不留图空洞）

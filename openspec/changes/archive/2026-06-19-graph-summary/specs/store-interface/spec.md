## ADDED Requirements

### Requirement: StoreInterface 图级元数据 kv 原语

`StoreInterface` SHALL 提供图级元数据 key-value 原语（图级、非节点字段）：

- `get_graph_meta(key: str) -> str | None` — 取图级 meta；key 不存在返回 None
- `set_graph_meta(key: str, value: str) -> None` — 写 / 覆盖图级 meta

图级 meta MUST NOT 作为节点 content / summary / extension；MUST NOT 进入节点活跃视图 token 口径。消费者（如 `GraphSummaryPlugin`、`MemoryStore`）经此原语读写图级元数据（如图摘要）。

#### Scenario: get 不存在 key 返回 None

- **WHEN** 调用 `get_graph_meta("absent")`
- **THEN** MUST 返回 None

#### Scenario: set 后 get 命中

- **WHEN** `set_graph_meta("graph_summary", "X")` 后 `get_graph_meta("graph_summary")`
- **THEN** MUST 返回 "X"

#### Scenario: set 覆盖

- **WHEN** 对同 key 两次 `set_graph_meta`
- **THEN** 后值 MUST 覆盖前值

---

### Requirement: 图级 meta 持久化（复用 meta 表）

`SQLiteStore` SHALL 复用既有通用 `meta(key TEXT PRIMARY KEY, value TEXT)` 表持久化图级 meta（与 provenance 同表、按 key 区分；图摘要 key = "graph_summary"），MUST NOT 新建独立表（最小改动，复用既有 kv 基础设施）。`set_graph_meta` 即时落库；跨实例 `initialize` + `load` 后 `get_graph_meta` MUST 保真。`InMemoryStore` 以 dict 承载、持久化钩子维持既有空操作语义。

#### Scenario: SQLite 跨实例 round-trip 保真

- **WHEN** 设若干图级 meta 后，新实例 `initialize` + `load`
- **THEN** 新实例 `get_graph_meta` MUST 与写入逐条一致

#### Scenario: 与 provenance 同表共存

- **WHEN** 写入图摘要且库含 provenance（`relation_model` 等）
- **THEN** 两者 MUST 同表共存、按 key 区分、互不覆盖

#### Scenario: InMemoryStore 承载 meta

- **WHEN** `InMemoryStore.set_graph_meta` 后 `get_graph_meta`
- **THEN** MUST 命中（dict 承载）

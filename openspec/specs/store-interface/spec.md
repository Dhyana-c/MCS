# store-interface Specification

## Purpose
定义统一存储抽象基类，合并图操作（CRUD + 查询）与持久化钩子（save/load/commit/save_full）为单一接口，使消费者（QueryEngine、WritePipeline、插件）依赖接口而非具体实现，支持未来扩展不同存储后端。

## Requirements

### Requirement: StoreInterface 定义统一存储抽象基类

`StoreInterface` SHALL 提供基于 `type`、支持关系边两端可达与 priority 排序的边 API：

**边 CRUD：**
- `add_edge(source_id, target_id, type="关联", priority=0.0) -> str` — `type` MUST ∈ 已登记类型（当前 `关联` / `互斥`）；MUST NOT 接受 `kind` / `label` 参数
- `delete_edge(edge_id)` / `update_edge(edge_id, **fields)` — 以**边 `id`** 为键
- `get_edges_between(source_id, target_id) -> list[Edge]` — 两节点间全部边

**下钻（组织骨架）查询：**
- `get_out_hierarchy(node_id, universe=None) -> list[Node]` — 该节点作组织中心时的下钻成员（由聚类涌现的关联 + hub 标记表达，驱动导航下钻）。**过滤语义 = 按 target 成员的 `universe` 单侧判定**（**非**"边两端同 universe"）：`universe=U` 时仅返回 `target.universe == U` 的成员；`universe=None` 时返回全部成员（**仅旧库兼容**）。对普通节点 A，传 `universe=A.universe` 时"单侧过滤"恰等价于"两端同 universe"；对 `__seed_root__`，`universe=U` 取 `target.universe==U` 的孤儿（**无视 root 自身是 `__reality__`**——孤儿挂 root 的边 `root(__reality__)→孤儿(<work_id>)` 本身即跨 universe 边，"边两端"措辞会误滤掉全部作品孤儿，故 MUST 用单侧语义）。**多 universe 库里所有 universe 孤儿挂同一根**，`universe=None` 返回全部（仅旧库兼容）；查询 / 守门 / 活跃视图渲染路径对 root（及任何节点）MUST 传当前 `universe`，否则视图混入其它 universe 成员、破坏单 universe 不变量。

**关系（两端可达）查询：**
- `get_relations(node_id, limit=None) -> list[Edge]` — 返回该节点作**任一端**的 `关联` / `互斥` 边（反查，供查询视图）。**取代 `get_facts` / `get_out_facts` / `get_assoc`**。**载重规则（双类过滤）**：
  - **同 universe 事件边**（对端 `node_class=事件` 且两端同 `universe`）：当 `node` 为**核心节点**（`node_class ∈ {概念, 事实}`）时 MUST 过滤；事件节点侧 `get_relations` 仍可达其连向核心的边（**单向过滤**）。
  - **跨 universe 边**（两端 `universe` 不同，含跨 universe 的事件背书边）：两端节点的 `get_relations` 都 MUST NOT 返回（**双向过滤**）——跨 universe 桥仅经显式定向查（`get_cross_universe_edges`，带 filter / pagination / limit）可达。
  - **Phase 2** 在过滤后的边集上按 `priority` 降序、`limit` 截断 top-K；**Phase 1** 返回全部（`limit` 仅作可选上限，两类载重过滤仍生效）。

**有界子图 BFS（`get_subgraph`）：** 沿关联出边邻接（`_assoc_out`）扩展、受 `T` 约束的活跃视图构建 MUST 按 universe 过滤——BFS 邻居扩展 MUST NOT 跨 universe（跨 universe 边 / 概念桥 MUST NOT 被 BFS 展开），否则 `link_cross_universe` 概念桥会让 BFS 跨 universe 扩展、破坏"单 universe 活跃视图 ≤ T"。`get_subgraph` 虽属正让位 agent 的框架版 BFS，但仍是 `StoreInterface` 契约、仍受 `T` 约束，本 change 阶段 MUST 补过滤。

**定向查事件（`get_related_events`，绕载重）：** 该原语绕载重规则、按需取连向节点的事件。本 change 引入跨 universe 事件背书边（`现实摄入 event(__reality__) —背书→ 作品 fact(<work_id>)`）后，对作品 fact 定向查 SHALL 返回其现实摄入背书事件（**跨 universe 亦返**——定向查本就绕载重，作品 fact 的出处确是那次现实摄入行为）。此语义 MUST 显式定义、不留白；universe 感知（参数分流）见「定向查事件按 universe 过滤」requirement（`work-narrative-events` 已落地）。

关系边 MUST **只存一份**（`主→宾`），两端邻接索引 MUST 都能取到；MUST NOT 双向对存、MUST NOT 提供 `bidirectional` / `direction` 参数。消费者 MUST 依赖 `StoreInterface` 而非具体实现。

#### Scenario: 消费者依赖统一接口

- **WHEN** `QueryEngine` 或 `WritePipeline` 初始化接收 store 参数
- **THEN** 参数类型 MUST 为 `StoreInterface`

#### Scenario: get_out_hierarchy 按 target 成员 universe 单侧过滤

- **WHEN** 节点 A（`universe=X`）有下钻成员 H（`universe=X`）、跨 universe 关联边到 C（`universe=Y`）
- **THEN** `get_out_hierarchy(A, universe="X")` MUST 只返回 H（`target.universe==X`），MUST NOT 返回 C
- **AND** `get_out_hierarchy(A)`（无参）返回全部成员（含 C，仅旧库兼容）——调用方 MUST 传 `universe`

#### Scenario: root 下钻按 universe 过滤（P8，单侧语义）

- **WHEN** `__seed_root__`（自身 `universe="__reality__"`）下挂 `"__reality__"` 孤儿与 `"三国演义"` 孤儿
- **THEN** `get_out_hierarchy(root, universe="三国演义")` MUST 返回 `"三国演义"` 孤儿（`target.universe=="三国演义"`，**即使 root→孤儿边跨 universe**）
- **AND** `get_out_hierarchy(root, universe="__reality__")` MUST 只返回 `"__reality__"` 孤儿
- **AND** `get_out_hierarchy(root)`（无参）返回全部孤儿（仅旧库兼容）
- **AND** 查询 / 守门路径 MUST 传 `universe`（多 universe 库 root 视图有界）

#### Scenario: add_edge 用 type、拒绝 kind/label

- **WHEN** 调用 `add_edge(A, B, type="互斥")`
- **THEN** 系统 MUST 创建一条 `type="互斥"` 边，两端邻接索引都可取到
- **AND** `add_edge` MUST NOT 接受 `kind` / `label` 参数

#### Scenario: get_relations 反查命中

- **WHEN** 存在关联边连 `小明` 与命题"小明喜欢苹果"
- **THEN** `get_relations(小明)` 与 `get_relations(该命题)` MUST 都包含这条边

#### Scenario: 关系边只存一份

- **WHEN** 写入一条关联 / 互斥边
- **THEN** 存储 MUST 只含一条边，MUST NOT 含其反向副本

#### Scenario: 核心节点不反查事件边

- **WHEN** 存在 `事件 —关联— 概念` 边（如"用户"概念连着某事件）
- **THEN** `get_relations("用户")` MUST NOT 返回该事件边（核心不反查事件）
- **AND** `get_relations(该事件)` MUST 返回该边（事件侧可达核心）
- **AND** 核心节点的 `priority` 截断 MUST 在排除事件边后的样本上进行

#### Scenario: 跨 universe 边双向过滤

- **WHEN** 存在两端 `universe` 不同的关联 / 互斥边
- **THEN** 两端节点的 `get_relations` MUST 都不含该边
- **AND** 该边仅经 `get_cross_universe_edges` 显式定向查可达

#### Scenario: get_edges_between 返回同对全部边

- **WHEN** 节点 A、B 间有多条边
- **THEN** `get_edges_between(A, B)` MUST 返回全部

#### Scenario: get_subgraph BFS 不跨 universe 扩展

- **WHEN** 节点 A（`universe=X`）经 `link_cross_universe` 概念桥连到 C（`universe=Y`），对 A 调 `get_subgraph`（带 universe 上下文 X）
- **THEN** BFS MUST NOT 经该概念桥展开到 C
- **AND** 活跃子图 MUST 只含 `universe=X` 节点（单 universe 有界）

#### Scenario: get_related_events 跨 universe 背书亦返

- **WHEN** 作品 fact（`universe=<work_id>`）有现实摄入背书事件（`universe=__reality__`），调 `get_related_events(该 fact)`
- **THEN** MUST 返回该现实摄入背书事件（定向查绕载重，跨 universe 亦返）
- **AND** 同一条边在 `get_relations(该 fact)` 中 MUST 被双向过滤（不进活跃视图）

---

### Requirement: InMemoryStore 实现 StoreInterface

系统 SHALL 提供 `InMemoryStore` 作为 `StoreInterface` 的默认实现，位于 `mcs/stores/in_memory.py`，使用 `dict` 存储节点/边/邻接关系。

#### Scenario: 持久化钩子为空操作

- **WHEN** 调用 `InMemoryStore.save()` 或 `InMemoryStore.load()`
- **THEN** MUST 为空操作（不报错，不持久化）

---

### Requirement: SQLiteStore 实现 StoreInterface

系统 SHALL 提供 `SQLiteStore` 作为 `StoreInterface` 的 SQLite 实现，位于 `mcs/stores/sqlite_store.py`，直接在 SQLite 上做图操作。

#### Scenario: 持久化钩子写入 SQLite

- **WHEN** 调用 `SQLiteStore.save()`
- **THEN** MUST 把当前图状态写入 SQLite 数据库

#### Scenario: load 从 SQLite 加载

- **WHEN** 调用 `SQLiteStore.load()`
- **THEN** MUST 从 SQLite 数据库加载节点和边到内存

---

### Requirement: 边持久化含 type / priority

边表 schema MUST 含 `id, source_id, target_id, type, priority`（`type` 取代 `kind` + `label`），PRIMARY KEY 为 `id`，并在 `source_id`、`target_id` 上建索引以支持两端可达查询。`save_full` / `load` round-trip MUST 逐条保真（含 `type` / `priority` / `extensions`）。

#### Scenario: 边表含 type 列

- **WHEN** 建表或落库边
- **THEN** 边记录 MUST 含 `(id, source_id, target_id, type, priority)`，MUST NOT 含 `kind` / `label` 列

#### Scenario: round-trip 保真

- **WHEN** 含关联边与互斥边的图 `save_full` 后 `load`
- **THEN** 加载的边集合 MUST 与落库前逐条一致（含 `type` / `priority`）

---

### Requirement: SQLiteStore 维护反向邻接表

`SQLiteStore` SHALL 维护反向邻接表 `_reverse_adjacency`（`target_id → {source_id}`），与正向邻接表 `_adjacency`（`source_id → {target_id}`）保持同步。任何改变图拓扑的操作（`add_edge` / `delete_edge` / `delete_node`）SHALL 同时更新正向与反向两张邻接表；`delete_node` 查找入边时 MUST 仅遍历 `_reverse_adjacency` 而非全表扫描；`load()` 从持久层重建图后 SHALL 重建 `_reverse_adjacency` 使其与 `_adjacency` 一致。

#### Scenario: add_edge 同步更新反向索引

- **WHEN** `add_edge(A, B)` 被调用
- **THEN** MUST 同时更新 `_adjacency[A].add(B)` 和 `_reverse_adjacency[B].add(A)`

#### Scenario: delete_edge 同步更新反向索引

- **WHEN** `delete_edge(A, B)` 被调用
- **THEN** MUST 同时更新 `_adjacency[A].discard(B)` 和 `_reverse_adjacency[B].discard(A)`

#### Scenario: delete_node 使用反向索引查找入边

- **WHEN** `delete_node(X)` 查找指向 X 的入边
- **THEN** MUST 仅遍历 `_reverse_adjacency.get(X, set())` 中的节点；MUST NOT 遍历 `self._adjacency` 的全部键

#### Scenario: load 时重建反向索引

- **WHEN** `SQLiteStore.load()` 从持久层加载图数据
- **THEN** MUST 在加载完成后重建 `_reverse_adjacency`，使其与 `_adjacency` 保持一致

---

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

- **WHEN** 写入图摘要且库含 provenance（`schema_version` 等）
- **THEN** 两者 MUST 同表共存、按 key 区分、互不覆盖

#### Scenario: InMemoryStore 承载 meta

- **WHEN** `InMemoryStore.set_graph_meta` 后 `get_graph_meta`
- **THEN** MUST 命中（dict 承载）

---

### Requirement: 节点表 schema 含 universe 列

`SQLiteStore` 节点表 schema MUST 含 `universe` 列（默认 `"__reality__"`），并在 `universe` 上建索引以支持按世界过滤查询。打开旧库（无 `universe` 列）时 MUST 经既有"打开时补列"机制补列、全部填默认 `"__reality__"`（行为与升级前等价——旧库隐含单一现实世界）。`save_full` / `load` round-trip MUST 逐条保真 `universe`。`InMemoryStore` 以 `Node.universe` 字段承载。

#### Scenario: 节点表含 universe 列

- **WHEN** 建表或落库节点
- **THEN** 节点记录 MUST 含 `universe`（默认 `"__reality__"`），并在 `universe` 上有索引

#### Scenario: 旧库打开补默认

- **WHEN** 打开无 `universe` 列的旧库
- **THEN** MUST 补列并全部填 `"__reality__"`
- **AND** 行为 MUST 与升级前等价（旧库所有节点归现实世界）

#### Scenario: universe round-trip 保真

- **WHEN** 含多 universe 节点的图 `save_full` 后 `load`
- **THEN** 加载的节点 `universe` MUST 与落库前逐条一致

---

### Requirement: 跨 universe 桥定向查原语

`StoreInterface` SHALL 提供 `get_cross_universe_edges(node_id, limit=None) -> list[Edge]`——绕过载重过滤、返回该节点作**任一端**的、对端 `universe` 不同的 `关联` / `互斥` 边，供显式跨 universe 查询工具受控取数（带 `limit`）。`InMemoryStore` 与 `SQLiteStore` 双实现 MUST 一致。该原语是跨 universe 桥**唯一**的默认载重之外可达路径。

#### Scenario: 定向查取跨 universe 桥

- **WHEN** 节点 A 有跨 universe 边到 B（不同 universe）
- **THEN** `get_cross_universe_edges(A)` MUST 返回该边（绕载重）
- **AND** `get_relations(A)` MUST NOT 返回该边（载重双向过滤）

#### Scenario: 双实现一致

- **WHEN** 同一图分别用 `InMemoryStore` 与 `SQLiteStore`
- **THEN** `get_cross_universe_edges` 返回结果 MUST 一致

### Requirement: 定向查事件按 universe 过滤

`StoreInterface` SHALL 提供 `get_related_events(node_id, universe=None, limit=None) -> list[Node]`——绕过载重规则、返回背书此核心节点的事件（时间倒排 + `limit` 截断）。**`universe` 参数过滤按参数分流，MUST NOT 改既有默认语义**：

- **`universe=None`（默认）返回全部背书事件（含跨 universe）**——`multi-universe-graph` 已实现并测试锁定"`get_related_events(作品 fact)` 无参跨 universe 亦返（查出处：该 fact 经哪次现实摄入进来）"。本语义 MUST 保持（`None` 全返），MUST NOT 改成"从节点继承 universe"——否则砍掉作品 fact 出处查询。
- **传 `universe=U` 时才只返 `node.universe==U` 的事件**——叙事时间线（作品 universe）MUST 显式传 `universe=work_id`，避免作品纪年（非 ISO）经 ISO 排序坏掉。

时间倒排仅在 `universe="__reality__"` 内保证（ISO 可比）；作品 universe 的事件排序由叙事时间线视图（`unified-graph-schema`）负责。`event_sort_key` 对非 ISO timestamp（作品纪年）MUST 容错（不抛）并做**数字年最小解析**（纯数字纪年可排；混合 / 非数字纪年如"建安五年"垫底，Phase 2 归一化）。`InMemoryStore` 与 `SQLiteStore` 双实现 MUST 一致。

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

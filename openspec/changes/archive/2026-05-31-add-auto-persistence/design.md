## Context

当前 GraphStore 是纯内存实现，SQLiteStoragePlugin 提供了 `save(graph)` / `load()` 手动全量快照接口。WritePipeline 的 6 段管线在阶段 ⑤ 图更新完成后不会触发任何持久化操作，数据只存在于内存中。

现有代码：
- `StorageInterface` 已定义 `save_node(node)` / `save_edge(edge)` 增量接口
- `SQLiteStoragePlugin` 已实现这两个接口
- `WritePipeline._apply_decisions()` 返回 `changed: list[Node]`，但未调用 storage
- `MCS.initialize()` 不执行 load-on-startup

批量摄入场景（如 HotpotQA 7405 条）下，中途崩溃意味着全部重来。

## Goals / Non-Goals

**Goals:**
- 每次写入后自动将变更的节点和边增量持久化到 StorageInterface
- MCS 启动时若图为空且 StorageInterface 可用，自动加载已有数据
- 支持配置开关控制自动落盘行为
- 最小改动：复用现有 StorageInterface 的 save_node / save_edge，不引入新存储抽象

**Non-Goals:**
- 不实现 WAL / 事务日志等高级持久化机制
- 不实现增量快照或时间旅行
- 不改造 GraphStore 为磁盘优先架构（保持内存图 + 落盘同步的模式）
- 不实现异步落盘（Phase 1 同步写入即可）

## Decisions

### D1: 落盘触发点——WritePipeline 末尾而非插件

**选择**：在 `WritePipeline.ingest()` 的阶段 ⑥ 之后增加阶段 ⑦ 自动落盘，直接调用 StorageInterface。

**备选**：通过 PostprocessPlugin（position=write_postprocess）实现。

**理由**：落盘是写入管线的固有需求而非可选后处理。用插件实现会增加不必要的间接层（需要从 PluginManager 查找 StorageInterface），且容易被误配置移除。直接在管线中调用更清晰、更可靠。保留 PostprocessPlugin 的 write_postprocess 挂载点供用户自定义后处理使用。

### D2: 增量落盘而非全量快照

**选择**：每次 ingest 只持久化 `ctx.changed` 中的节点和关联边（增量）。

**备选**：每次 ingest 后调用 `storage.save(graph)` 全量快照。

**理由**：增量落盘 I/O 量与变更量成正比。全量快照在图规模增大后（HotpotQA 可能产生数万节点）每次都重写全表，性能不可接受。

### D3: load-on-startup 在 MCS.initialize() 中执行

**选择**：MCS.initialize() 末尾检查 StorageInterface，若存在且图中无节点则调用 `storage.load()` 填充 graph。

**备选**：让用户手动调用 `mcs.load()`。

**理由**：自动加载减少使用门槛，且仅在图为空时触发，不会覆盖已有内存数据。手动加载作为逃生口仍可通过 `get_plugin("sqlite_storage").load()` 实现。

### D4: 边的增量落盘通过变更节点的邻接关系推导

**选择**：阶段 ⑤ 的 `_apply_decisions` 中 create 动作会调用 `graph.add_edge()`。在阶段 ⑦ 落盘时，遍历 `ctx.changed` 中每个节点的邻居，如果边的另一端也在 changed 中，则落盘该边。

**备选**：在 WriteContext 中新增 `changed_edges` 字段追踪变更边。

**理由**：新增字段最准确但改动面大（需要修改 `_apply_decisions` 的每个分支）。当前 Phase 1 的边变更场景有限（create 时连边），从 changed 节点推导足够。若后续 Phase 2 有复杂边操作再扩展。

### D5: 配置开关 auto_persist

**选择**：MCSConfig 增加 `auto_persist: bool = True`。WritePipeline 读取该配置决定是否执行 ⑦。

**理由**：某些测试场景（mock 模式）不需要落盘，开关提供灵活性。默认开启确保生产使用安全。

## Risks / Trade-offs

- **[边遗漏风险]** 从 changed 节点推导边可能遗漏 merge/attach 场景中已有边 → 缓解：merge/attach 不创建新边，create 的边通过邻接推导可覆盖
- **[并发安全]** SQLite 在多进程写入时可能锁定 → Phase 1 单进程模型，暂不处理
- **[性能]** 每次 ingest 同步写磁盘增加延迟 → 可接受，SQLite 单次写入通常 <1ms；未来可改为批量提交
- **[load 与内存图冲突]** 若 initialize 时 graph 已有数据（手动 add_node），load 不覆盖 → 仅在 `len(graph) == 0` 时加载

## Why

当前 `GraphStore` 直接使用 `dict` 存储节点/边/邻接关系，计算逻辑与存储实现紧耦合。这导致：
1. 无法切换存储后端（如换 PostgreSQL、图数据库）
2. 无法在存储层直接做计算（必须全量加载到内存）
3. SQLite 只作为持久化快照，未发挥其查询能力

现在做这个抽象是因为：项目需要支持更大规模图（>10万节点），且未来可能需要多后端支持。

## What Changes

- **新增 `GraphStoreInterface` 接口**：抽象基类，定义全部图操作方法（读写一体化）
- **重构 `InMemoryGraphStore`**：当前 `GraphStore` 改名，用 dict 实现 `GraphStoreInterface` 接口
- **保留 `StorageInterface`**：作为持久化快照接口（save/load），与 `GraphStoreInterface` 正交
- **保留 `GraphStore = InMemoryGraphStore` 别名**：向后兼容

## Capabilities

### New Capabilities

- `graph-store-interface`: 可读写图存储接口，定义全部图操作方法（节点/边的 CRUD + 查询）

### Modified Capabilities

无。`StorageInterface` 保持不变，`GraphStoreInterface` 是新增接口。

## Impact

- **核心文件**：
  - `mcs/core/graph.py` — 拆分为 `graph.py`（Node/Edge/Subgraph 数据类）+ `graph_store.py`（接口 + 实现）
- **依赖方**：
  - `mcs/core/query_engine.py` — 类型标注改为 `GraphStoreInterface`
  - `mcs/core/write_pipeline.py` — 类型标注改为 `GraphStoreInterface`
  - 所有插件 — 通过 `PluginContext` 获取 `GraphStoreInterface`
- **测试**：运行验证，无需大改（别名保证兼容）

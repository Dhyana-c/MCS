## Why

当前存在两个存储抽象：`GraphStoreInterface`（图操作 CRUD + 查询）和 `StorageInterface`（持久化 save/load），职责重叠且概念割裂。同时 `InMemoryGraphStore` 放在 `core/` 中违反了"core 只含接口和数据类"的原则。统一后，一个存储后端只需实现一个接口，减少概念复杂度。

## What Changes

- **合并 `GraphStoreInterface` 和 `StorageInterface` 为统一的 `StoreInterface`**：图操作（CRUD + 查询）+ 持久化钩子（save/load/commit）在一个接口中
- **`InMemoryGraphStore` 移出 core** → `mcs/stores/in_memory.py`
- **`SQLiteStoragePlugin` 重构为 `SQLiteStore`**：直接实现 `StoreInterface`，不再需要独立的 `StorageInterface` 插件
- **删除 `StorageInterface`**：职责已合并到 `StoreInterface`
- **`core/graph_store.py` 重命名为 `core/store.py`**：只保留 `StoreInterface` ABC
- **BREAKING**: `StorageInterface` 被移除，`SQLiteStoragePlugin` 改名为 `SQLiteStore`

## Capabilities

### New Capabilities

- `store-interface`: 统一存储接口，合并图操作 + 持久化为一个 ABC

### Modified Capabilities

- `graph-store-interface`: 合并到 `store-interface`，原 spec 废弃
- `plugin-protocol`: `StorageInterface` 插件类型移除，`SQLiteStore` 不再是 Plugin 子类

## Impact

- **核心文件**：
  - `mcs/core/graph_store.py` → 删除（接口移到 `core/store.py`）
  - `mcs/core/store.py` — 新增 `StoreInterface` ABC
  - `mcs/stores/in_memory.py` — `InMemoryStore` 实现（从 `core/graph_store.py` 迁出）
  - `mcs/stores/sqlite_store.py` — `SQLiteStore` 实现（从 `plugins/phase1/sqlite_storage.py` 迁出）
  - `mcs/interfaces/storage.py` — 删除
- **依赖方**：
  - 所有消费 `GraphStoreInterface` 的代码改为 `StoreInterface`
  - 所有消费 `StorageInterface` 的代码改为 `StoreInterface`
  - `PluginType.STORAGE` 不再需要，`PluginContext` 改为持有 `StoreInterface` 实例
- **测试**：需要更新所有相关测试

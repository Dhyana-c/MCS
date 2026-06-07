## REMOVED Requirements

### Requirement: GraphStoreInterface 定义图操作抽象基类

**Reason**: 合并到 `StoreInterface`（unified-storage-abstraction）

**Migration**: 使用 `StoreInterface` 替代 `GraphStoreInterface`

---

### Requirement: InMemoryGraphStore 实现 GraphStoreInterface

**Reason**: 移出 core 并重命名为 `InMemoryStore`（位于 `mcs/stores/in_memory.py`）

**Migration**: 使用 `InMemoryStore` 替代 `InMemoryGraphStore`

---

### Requirement: 向后兼容别名

**Reason**: 不再需要向后兼容，breaking change 可接受

**Migration**: 直接使用新类型名称

---

### Requirement: StorageInterface 接收 GraphStoreInterface

**Reason**: `StorageInterface` 已合并到 `StoreInterface`

**Migration**: 不再需要此 requirement

---

### Requirement: PluginContext.graph 类型为 GraphStoreInterface

**Reason**: 改为 `PluginContext.store` 类型为 `StoreInterface`

**Migration**: 使用 `PluginContext.store` 替代 `PluginContext.graph`
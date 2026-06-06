## REMOVED Requirements

### Requirement: PluginType.STORAGE

**Reason**: 存储不再是插件类型，而是核心组件

**Migration**: MCS 直接持有 `StoreInterface` 实例，不通过 `PluginManager` 管理

---

## MODIFIED Requirements

### Requirement: PluginContext 支持新插件接口的注册与查找

`PluginManager` SHALL provide registration and lookup for all 4 new plugin interfaces (Entry, Trim, Arbitration, Postprocess, Compaction), and maintain priority-sorted lists for those that need ordering. `PluginContext` SHALL hold a `store: StoreInterface` attribute instead of `graph: GraphStoreInterface`.

#### Scenario: PluginContext 持有 StoreInterface

- **WHEN** `PluginContext` 初始化
- **THEN** MUST 包含 `store: StoreInterface` 属性

#### Scenario: 插件通过 context.store 访问存储

- **WHEN** 插件通过 `context.store` 访问存储
- **THEN** 类型 MUST 为 `StoreInterface`
# plugin-protocol Specification Delta

## ADDED Requirements

### Requirement: PluginType 枚举包含 SEED_SELECTOR

The system SHALL include `SEED_SELECTOR = "seed_selector"` in the `PluginType` enum defined in `mcs/core/plugin.py`.

#### Scenario: 按类型查找种子选择器

- **WHEN** 调用 `plugin_manager.get_all(PluginType.SEED_SELECTOR)`
- **THEN** 返回值 MUST 是所有注册的 SEED_SELECTOR 类型插件，按 `get_priority()` 降序排列

---

### Requirement: 提供 SeedSelectorPluginInterface 用于种子筛选

The system SHALL define `SeedSelectorPluginInterface` with abstract method `select(seeds: List[Node], query: str, budget: int, ctx) -> List[Node]`. This interface MUST be used for query pipeline stage ② seed selection after TrimPlugin.

#### Scenario: 接口最小契约

- **WHEN** 实现一个 SeedSelectorPlugin
- **THEN** 子类 MUST 提供 `select` 方法；`select` MUST 返回 `List[Node]`；`get_type()` MUST 返回 `PluginType.SEED_SELECTOR`

#### Scenario: select 输出满足预算约束

- **WHEN** SeedSelectorPlugin.select 完成
- **THEN** 返回节点的估算 token 总和 MUST ≤ `budget`

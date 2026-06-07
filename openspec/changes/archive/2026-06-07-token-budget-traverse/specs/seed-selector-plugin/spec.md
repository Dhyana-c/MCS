# seed-selector-plugin Specification

## Purpose
定义种子选择器插件接口，用于查询管线阶段 ② 的种子筛选、排序和预算截断。支持多路召回策略的插件化扩展。

## Requirements

### Requirement: SeedSelectorPluginInterface 继承 Plugin 并返回 SEED_SELECTOR 类型

The system SHALL define `SeedSelectorPluginInterface` inheriting `Plugin`, with `get_type()` returning `PluginType.SEED_SELECTOR`, and an abstract `select(seeds: List[Node], query: str, budget: int, ctx) -> List[Node]` method. `execute()` SHALL delegate to `select()`.

#### Scenario: 接口最小契约

- **WHEN** 实现一个 SeedSelectorPlugin
- **THEN** 子类 MUST 提供 `select` 方法；`select` MUST 返回 `List[Node]`；`get_type()` MUST 返回 `PluginType.SEED_SELECTOR`

#### Scenario: select 输出满足预算约束

- **WHEN** SeedSelectorPlugin.select 完成
- **THEN** 返回节点的估算 token 总和 MUST ≤ `budget`

#### Scenario: select 保持或调整顺序

- **WHEN** SeedSelectorPlugin.select 返回节点列表
- **THEN** 列表顺序 MUST 反映相关性优先级（高相关性在前）；允许重排输入顺序

---

### Requirement: PluginType 枚举包含 SEED_SELECTOR

The system SHALL include `SEED_SELECTOR = "seed_selector"` in the `PluginType` enum defined in `mcs/core/plugin.py`.

#### Scenario: 按类型查找种子选择器

- **WHEN** 调用 `plugin_manager.get_all(PluginType.SEED_SELECTOR)`
- **THEN** 返回值 MUST 是所有注册的 SEED_SELECTOR 类型插件，按 `get_priority()` 降序排列

---

### Requirement: 种子定位阶段增加 SeedSelectorPlugin 链

The system SHALL modify `QueryEngine._locate_seeds` to execute SeedSelectorPlugin chain after TrimPlugin. The chain SHALL be serial: each plugin's output becomes the next plugin's input.

#### Scenario: 执行顺序为 Entry → Trim → SeedSelector

- **WHEN** 查询管线执行阶段 ②
- **THEN** 执行顺序 MUST 是：EntryPlugin 链（合并）→ TrimPlugin（硬截断）→ SeedSelectorPlugin 链（语义筛选）

#### Scenario: SeedSelector 链可空

- **WHEN** 未配置任何 SeedSelectorPlugin
- **THEN** 框架 MUST 跳过语义筛选步骤，直接返回 TrimPlugin 输出

#### Scenario: 多个 SeedSelector 串联

- **WHEN** 配置多个 SeedSelectorPlugin [S1, S2]
- **THEN** 框架 MUST 调用 S1(seeds, query, budget, ctx) → S2(S1输出, query, budget, ctx)；返回 S2 的输出

---

### Requirement: 默认提供 LLMSeedSelectorPlugin 实现

The system SHALL provide a default `LLMSeedSelectorPlugin` with `priority=0`, which uses LLM to select relevant seeds based on query semantics.

#### Scenario: LLMSeedSelector 使用 select_nodes purpose

- **WHEN** LLMSeedSelectorPlugin.select 被调用
- **THEN** 插件 MUST 调用 `llm.call(purpose="select_nodes", nodes_in=seeds, free_args={"query": query, "accumulated_summary": ""})` 获取选中种子 ID

#### Scenario: LLMSeedSelector 可配置

- **WHEN** 用户希望自定义种子筛选策略
- **THEN** 用户 MUST 能通过配置禁用默认 LLMSeedSelector，注册自定义 SeedSelectorPlugin

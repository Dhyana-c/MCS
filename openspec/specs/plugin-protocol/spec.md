# plugin-protocol Specification

## Purpose
定义插件体系基类 Plugin 与 PluginType 枚举，以及各阶段插件接口（Entry、Trim、Arbitration、Preprocess、Postprocess、Compaction、Index、LLM、NodeExtension 等），统一插件注册与生命周期管理。
## Requirements
### Requirement: 提供 EntryPluginInterface 用于种子定位

The system SHALL define `EntryPluginInterface` inheriting `Plugin`, with: `get_type()` returning `PluginType.ENTRY`, a `get_priority() -> int` method (descending = higher priority), an `exclusive` property (default False), and an abstract `locate(query: str, ctx) -> List[Node]` method. `execute()` SHALL delegate to `locate()`.

#### Scenario: 接口最小契约

- **WHEN** 实现一个 EntryPlugin
- **THEN** 子类 MUST 提供 `get_priority()`、`exclusive`、`locate` 三个成员；`locate` MUST 返回 `List[Node]`；`get_type()` MUST 返回 `PluginType.ENTRY`

#### Scenario: priority 决定合并顺序

- **WHEN** 框架合并多个 EntryPlugin 的输出
- **THEN** 合并结果 MUST 按 `get_priority()` 降序排列；同 priority 的相对顺序由注册顺序决定

#### Scenario: exclusive 短路语义

- **WHEN** 高优先级插件返回非空且 `exclusive=True`
- **THEN** 框架 MUST 不调用比它优先级低的 EntryPlugin

---

### Requirement: _locate_seeds 对每个 EntryPlugin 异常隔离

`QueryEngine._locate_seeds` SHALL 对每个 EntryPlugin 的 `locate` 调用包裹独立的 try/except。单个插件抛异常时 MUST log 警告并继续执行后续插件，MUST NOT 拖垮整次种子定位。

#### Scenario: 单插件异常不影响其他插件

- **WHEN** EntryPlugin A（priority=100）抛出异常，EntryPlugin B（priority=80）正常
- **THEN** 框架 MUST 记录 A 的异常日志，继续执行 B 并合并 B 的候选节点

#### Scenario: 所有插件异常时返回空种子

- **WHEN** 所有 EntryPlugin 均抛出异常
- **THEN** 框架 MUST 返回空 `seeds`；后续遍历 MUST 自然终止

#### Scenario: 异常日志包含插件名和错误信息

- **WHEN** EntryPlugin "alias_index" 的 locate 方法抛出 ValueError
- **THEN** 框架 MUST log 包含 "alias_index" 和错误信息的 WARNING 级别日志

---

### Requirement: 提供 TrimPluginInterface 用于统一裁剪

The system SHALL define `TrimPluginInterface` with abstract method `trim(nodes: List[Node], budget: int, *, query: str = "", ctx = None) -> List[Node]`. TrimPlugin 采用链式语义：可注册多个实现，按优先级排序依次执行。此接口 MUST be reusable at both stage ② (seed trimming) and as the underlying implementation of `PriorityArbitrationPlugin` at stage ④.

#### Scenario: trim 不破坏顺序语义（基本实现）

- **WHEN** TrimPlugin.trim 接收按优先级排序的 nodes 列表
- **THEN** 基本实现（如 PriorityTrimPlugin）返回的子集 MUST 保持原顺序（不重排）

#### Scenario: trim 满足预算约束

- **WHEN** TrimPlugin.trim 完成
- **THEN** 返回 nodes 的估算 token 总和 MUST ≤ `budget`

#### Scenario: TrimPlugin 链式调用

- **WHEN** 注册了多个 TrimPlugin [T1, T2]（按优先级降序）
- **THEN** 框架 MUST 依次调用 T1.trim(nodes, budget, query, ctx) → T2.trim(T1输出, budget, query, ctx)

#### Scenario: TrimPlugin 可挂载在多个位置

- **WHEN** 同一个 TrimPlugin 实例同时被读流程 ② 和（通过 PriorityArbitrationPlugin 包装后）④ 引用
- **THEN** 框架 MUST 允许此种复用，不要求每个挂载点持有独立实例

#### Scenario: 语义 TrimPlugin 使用 query 参数

- **WHEN** SemanticTrimPlugin.trim 被调用且 query 非空
- **THEN** 插件 MAY 使用 LLM 按 query 语义筛选节点（可重排）；MUST 满足预算约束

---

### Requirement: 废弃 SeedSelectorPluginInterface

`SeedSelectorPluginInterface` SHALL be deprecated. 语义筛选已合并为 TrimPlugin 实现（如 `SemanticTrimPlugin`）。`SeedSelectorPluginInterface` 和 `PluginType.SEED_SELECTOR` SHALL remain for one version then be removed.

#### Scenario: 废弃接口仍可导入

- **WHEN** 旧代码导入 `SeedSelectorPluginInterface`
- **THEN** MUST 成功导入但类文档 MUST 标注 deprecated

#### Scenario: SEED_SELECTOR 枚举值仍可用

- **WHEN** 使用 `PluginType.SEED_SELECTOR`
- **THEN** MUST 等价于 `"seed_selector"` 但枚举文档 MUST 标注 deprecated

---

### Requirement: 提供 ArbitrationPluginInterface 用于读流程仲裁

The system SHALL define `ArbitrationPluginInterface` with abstract method `arbitrate(accumulated: List[Node], query: str, ctx) -> List[Node]`. Each query pipeline configuration accepts AT MOST one instance.

#### Scenario: 输入输出均为节点集合

- **WHEN** 检查 ArbitrationPluginInterface 签名
- **THEN** 输入 MUST 是 `List[Node]`；输出 MUST 也是 `List[Node]`

#### Scenario: 配置多个仲裁插件报错

- **WHEN** 用户配置中注册 ≥2 个 ArbitrationPlugin
- **THEN** PluginManager 在初始化阶段 MUST 抛出配置错误

---

### Requirement: 提供 WritePreprocessPluginInterface 用于写入管线前置处理

The system SHALL define `WritePreprocessPluginInterface` inheriting `Plugin`, with abstract method `preprocess(text: str, ctx: WriteContext) -> str`. This interface MUST be used for write pipeline stage ① (text preprocessing such as source tracking, summarization, text cleaning). `get_type()` MUST return `PluginType.WRITE_PREPROCESS`. WritePreprocessPlugin MUST NOT control pipeline flow (e.g. skip); idempotency checks SHALL be the caller's responsibility.

#### Scenario: 接口最小契约

- **WHEN** 实现一个 WritePreprocessPlugin
- **THEN** 子类 MUST 提供 `preprocess` 方法；`preprocess` MUST 返回 `str`；`get_type()` MUST 返回 `PluginType.WRITE_PREPROCESS`

#### Scenario: 链式调用语义

- **WHEN** 配置多个 WritePreprocessPlugin [P1, P2]
- **THEN** 框架 MUST 调用 P1(text) → P2(P1输出)；返回 P2 的输出

#### Scenario: 按类型查找写入前置插件

- **WHEN** 调用 `plugin_manager.get_all(PluginType.WRITE_PREPROCESS)`
- **THEN** 返回值 MUST 是所有注册的 WRITE_PREPROCESS 类型插件

---

### Requirement: 提供 QueryPreprocessPluginInterface 用于查询管线前置处理

The system SHALL define `QueryPreprocessPluginInterface` inheriting `Plugin`, with abstract method `preprocess(text: str, ctx: QueryContext) -> str`. This interface MUST be used for query pipeline stage ① (query rewriting, synonym expansion, intent recognition). `get_type()` MUST return `PluginType.QUERY_PREPROCESS`.

#### Scenario: 接口最小契约

- **WHEN** 实现一个 QueryPreprocessPlugin
- **THEN** 子类 MUST 提供 `preprocess` 方法；`preprocess` MUST 返回 `str`；`get_type()` MUST 返回 `PluginType.QUERY_PREPROCESS`

#### Scenario: 链式调用语义

- **WHEN** 配置多个 QueryPreprocessPlugin [P1, P2]
- **THEN** 框架 MUST 调用 P1(text) → P2(P1输出)；返回 P2 的输出

#### Scenario: 按类型查找查询前置插件

- **WHEN** 调用 `plugin_manager.get_all(PluginType.QUERY_PREPROCESS)`
- **THEN** 返回值 MUST 是所有注册的 QUERY_PREPROCESS 类型插件

---

### Requirement: 废弃 PreprocessPluginInterface

`PreprocessPluginInterface` SHALL be deprecated in favor of `WritePreprocessPluginInterface` and `QueryPreprocessPluginInterface`. It SHALL remain as an alias for `WritePreprocessPluginInterface` with a `DeprecationWarning` on import. It SHALL be removed after one version.

#### Scenario: 废弃别名仍可用

- **WHEN** 旧代码导入 `PreprocessPluginInterface`
- **THEN** MUST 得到 `WritePreprocessPluginInterface` 的别名

#### Scenario: 导入时发出警告

- **WHEN** 导入 `PreprocessPluginInterface`
- **THEN** MUST 发出 `DeprecationWarning`

#### Scenario: PREPROCESS 枚举值指向 WRITE_PREPROCESS

- **WHEN** 使用 `PluginType.PREPROCESS`
- **THEN** MUST 等价于 `PluginType.WRITE_PREPROCESS`

---

### Requirement: 提供 PostprocessPluginInterface 用于后置处理

The system SHALL define `PostprocessPluginInterface` with abstract method `process(input: Any, ctx) -> Any`. The interface MUST NOT constrain input/output type beyond being chainable.

#### Scenario: 输入输出类型自由

- **WHEN** 实现 PostprocessPlugin
- **THEN** 子类 MUST 能声明任意输入类型与任意输出类型；框架 MUST 不强制类型断言

#### Scenario: 多个 PostprocessPlugin 可串联

- **WHEN** 配置中注册多个 PostprocessPlugin
- **THEN** 框架 MUST 按注册顺序串行调用；前一个的输出作为后一个的输入

#### Scenario: PostprocessPlugin 不再有 position 属性

- **WHEN** 检查 `PostprocessPluginInterface` 定义
- **THEN** MUST NOT 存在 `position` 属性或 `@property def position(self) -> str` 方法

#### Scenario: 管线不依赖 position 筛选

- **WHEN** 检查 `QueryEngine` 和 `WritePipeline` 的 `_run_preprocess` 方法
- **THEN** 代码 MUST NOT 包含 `getattr(p, "position", ...)` 相关逻辑

---

### Requirement: 提供 CompactionPluginInterface 用于写流程压缩

The system SHALL define `CompactionPluginInterface` with: `should_run(changed_nodes, graph) -> bool`, `run(changed_nodes, graph, llm_caller) -> None`, and `guard(node, store, llm_caller) -> None`. Only plugins whose `should_run` returns True execute `run()`. The `guard` method performs invariant checking and compaction for a single node that may exceed budget; it has a default no-op implementation so existing plugins are unaffected.

#### Scenario: should_run 短路 run

- **WHEN** 某 CompactionPlugin 的 should_run 返回 False
- **THEN** 框架 MUST 不调用该插件的 run

#### Scenario: run 可获得 LLM 调用句柄

- **WHEN** CompactionPlugin.run 被调用
- **THEN** 框架 MUST 传入 `llm_caller`（统一调用模式的入口）；插件可用它执行 `decide_hub` 等 purpose

#### Scenario: guard 默认为空操作

- **WHEN** CompactionPlugin 未覆写 `guard` 方法
- **THEN** 默认实现 MUST 为空操作（不执行任何检查或压缩）

#### Scenario: guard 被 _guard_invariant 遍历调用

- **WHEN** `_guard_invariant` 检查超预算节点
- **THEN** MUST 遍历所有 CompactionPlugin 并调用 `guard(node, store, llm_caller)`；MUST NOT import 具体插件类（如 FanoutReducerPlugin）或调用其私有方法

#### Scenario: FanoutReducerPlugin 覆写 guard

- **WHEN** FanoutReducerPlugin 实现了 `guard`
- **THEN** 该方法 MUST 内部调用预算检查（原 `_exceeds_budget` 逻辑）和裂变压缩（原 `_compact_node` 逻辑）

---

### Requirement: 删除旧 PipelineHookInterface 与 QueryHookInterface

The system SHALL NOT include `PipelineHookInterface` or `QueryHookInterface` (the old 9+7 state-point hook model). All extension points that previously used these hooks SHALL be migrated to the 5 new plugin interfaces.

#### Scenario: 旧接口文件不存在

- **WHEN** 列出 `mcs/interfaces/` 目录
- **THEN** MUST NOT 存在 `pipeline_hook.py` 或 `query_hook.py`（在下游 Phase 1 实现 change 落地后）

#### Scenario: 旧 9+7 状态点概念不再出现

- **WHEN** 审查 capability spec 与文档
- **THEN** MUST NOT 含"INGEST_START / EXTRACTED / PLACE_START / ANCHORS_FOUND / EXISTENCE_CHECKED / CREATED_OR_MERGED / FANOUT_CHECKED / PLACE_END / INGEST_END" 等 9 状态点命名；MUST NOT 含"QUERY_START / SEEDS_LOCATED / TRAVERSE_START / TRAVERSE_STEP / TRAVERSE_END / SYNTHESIZE_START / QUERY_END" 等 7 状态点命名

#### Scenario: 迁移路径明确

- **WHEN** 一个原本依赖旧 hook 的插件（如旧 SourceTrackingPlugin 使用 `on_ingest_start` 做幂等检查）需要重写
- **THEN** 迁移路径 MUST 明确：幂等检查迁移到写前置 PreprocessPluginInterface；追加 source 迁移到 ⑤ 图更新后的压缩链或独立的 NodeExtension 钩子

---

### Requirement: NodeExtensionInterface 支持按 purpose 贡献渲染片段

The system SHALL extend `NodeExtensionInterface` (kept from original architecture) with an optional `render(node, purpose) -> str | None` method. ContextRenderer MUST consult each registered NodeExtension's `render` when serializing nodes for a given LLM purpose.

#### Scenario: 插件可选择性贡献

- **WHEN** ContextRenderer 渲染一个节点为 `purpose = synthesize` 的 prompt
- **THEN** 框架 MUST 遍历所有 NodeExtension；MUST 调用每个的 `render(node, "synthesize")`；返回 None 的插件不贡献片段

#### Scenario: 不同 purpose 的渲染贡献不同

- **WHEN** SourceTracking 插件实现 render
- **THEN** 它 MAY 在 `purpose = synthesize` 时返回出处片段（用户要溯源）；在 `purpose = decide_directions` 时返回 None（导航判方向不需要出处）

#### Scenario: 默认核心字段始终渲染

- **WHEN** ContextRenderer 渲染任意节点
- **THEN** `node.name` 和 `node.content`（或在 navigation purpose 下退化为 summary）MUST 始终被渲染；NodeExtension 的贡献是在核心字段之外的追加

---

### Requirement: 插件优先级排序与短路语义统一

For any plugin chain that supports priority (entry plugins, postprocess plugins), the system SHALL use the same semantics: priority obtained via `get_priority()` (descending order); tie-breaking by registration order; explicit `exclusive=True` on EntryPlugin short-circuits lower priorities; no implicit short-circuiting elsewhere.

#### Scenario: 同种插件链语义一致

- **WHEN** 实现 EntryPlugin chain 与 Postprocess chain
- **THEN** 两者 MUST 使用相同排序规则（`get_priority()` 降序）；MUST 仅 EntryPlugin 支持 `exclusive=True`（Postprocess 是串联管道而非选择器）

#### Scenario: 同 priority 行为稳定

- **WHEN** 两个插件 priority 相同
- **THEN** 框架 MUST 在同一配置下产生相同执行顺序；具体顺序由注册顺序决定（先注册者先执行）

---

### Requirement: PluginManager 支持新插件接口的注册与查找

`PluginManager` SHALL register and look up plugins by `PluginType` enum (not by interface class object). 它 SHALL 按 `plugin.get_types()` 把插件登记到每个类型下，并对需要排序的类型按 `get_priority()` 降序返回。

#### Scenario: 按类型查找

- **WHEN** 调用 `plugin_manager.get_all(PluginType.ENTRY)`
- **THEN** 返回值 MUST 是按 `get_priority()` 降序排列的所有 ENTRY 类型插件
- **AND** `plugin_manager.get(PluginType.ENTRY)` MUST 返回其中第一个（无则 None）

#### Scenario: 按名称查找

- **WHEN** 调用 `plugin_manager.get_by_name(name)`
- **THEN** MUST 返回该名称的插件实例（无则 None）

#### Scenario: ArbitrationPlugin 单例检查

- **WHEN** 注册第二个 `get_types()` 含 `PluginType.ARBITRATION` 的插件
- **THEN** PluginManager MUST 在 `register` 时抛 `ConfigurationError`

### Requirement: Plugin 顶级基类定义于 core/plugin.py

The system SHALL define a top-level `Plugin` abstract base class in `mcs/core/plugin.py` as the single root abstraction for all plugins. 所有接口与插件实现 SHALL 适配它；旧的 `mcs/plugins/base.py` 基类 SHALL 被删除，其职责由 `core/plugin.py` 接管。插件实现文件 SHALL 按其 `PluginType` 组织在 `mcs/plugins/<type>/` 目录下，而非 `mcs/plugins/phase1/`。

#### Scenario: Plugin 契约完整

- **WHEN** 检查 `mcs/core/plugin.py`
- **THEN** MUST 含 `Plugin` 类，具有抽象方法 `get_name() -> str`、`get_type() -> PluginType`、`execute(**kwargs) -> Any`
- **AND** MUST 提供具默认实现的 `get_types() -> set[PluginType]`（默认 `{get_type()}`）、`get_priority() -> int`（默认 0）、`initialize(context) -> None`（空操作）、`shutdown() -> None`（空操作）

#### Scenario: 旧基类不存在

- **WHEN** 检查 `mcs/plugins/base.py`
- **THEN** 该文件 MUST NOT 存在
- **AND** 任何模块 MUST NOT 从 `mcs.plugins.base` 导入 `Plugin`

#### Scenario: 插件按类型目录组织

- **WHEN** 检查 `mcs/plugins/` 目录结构
- **THEN** MUST NOT 存在 `phase1/` 或 `phase2/` 子目录
- **AND** 插件文件 MUST 位于 `mcs/plugins/<plugin_type>/` 对应目录下

---

### Requirement: PluginType 类型枚举

The system SHALL define a `PluginType` enum in `mcs/core/plugin.py`, inheriting `str` and `Enum`, enumerating all plugin roles. PluginManager 与管线代码 SHALL 用它作为索引与查找键，取代旧的 interface 类对象。

#### Scenario: PluginType 取值完整

- **WHEN** 检查 `PluginType`
- **THEN** MUST 继承 `str` 与 `Enum`
- **AND** MUST 含取值 ENTRY、TRIM、ARBITRATION、WRITE_PREPROCESS、QUERY_PREPROCESS、POSTPROCESS、COMPACTION、INDEX、LLM、NODE_EXTENSION、STORAGE_SCHEMA_EXT、MAINTENANCE、SEED_SELECTOR
- **AND** MAY 含废弃值 PREPROCESS（指向 WRITE_PREPROCESS）

#### Scenario: 管线按 PluginType 查找

- **WHEN** 检查 `core/write_pipeline.py`、`core/query_engine.py`、`core/context_renderer.py`
- **THEN** 所有 `plugin_manager.get()` / `get_all()` 调用 MUST 使用 `PluginType.XXX` 参数，而非 interface 类对象

#### Scenario: 目录名与 PluginType 对齐

- **WHEN** 检查 `mcs/plugins/` 下的子目录名
- **THEN** 每个子目录名 MUST 对应 `PluginType` 的一个小写枚举值（如 `entry` 对应 `ENTRY`）

---

### Requirement: 接口层继承 Plugin 且不反向依赖 core 管理器

所有接口（`EntryPluginInterface` 等）SHALL 继承 `core/plugin.py` 的 `Plugin`，实现 `get_type()` 返回对应 `PluginType`，并以 `execute()` 委托其核心方法。接口层 SHALL NOT 依赖 `core/plugin_manager`。

#### Scenario: 接口继承 Plugin

- **WHEN** 检查任意接口文件（如 `interfaces/entry_plugin.py`）
- **THEN** 该接口类 MUST 继承 `Plugin`
- **AND** MUST 实现 `get_type()` 返回对应 `PluginType`
- **AND** MUST 以 `execute()` 委托其核心方法（无统一执行语义者 MAY 抛 `NotImplementedError`）

#### Scenario: 接口不导入 plugin_manager

- **WHEN** 检查 `interfaces/` 下所有文件的非 TYPE_CHECKING 导入
- **THEN** MUST NOT 导入 `mcs.core.plugin_manager`

---

### Requirement: 多接口插件通过 get_types 登记全部类型

实现多个接口的插件 SHALL 覆写 `get_types()` 返回其全部 `PluginType`，使 PluginManager 能按其中任意类型索引到它；`PluginManager.register()` SHALL 按 `get_types()` 把插件登记到每个类型下。

#### Scenario: 多接口插件可被每个类型查找

- **WHEN** 一个插件同时实现 NodeExtension 与 StorageSchemaExtension（如 SourceTracking），其 `get_types()` 返回 `{NODE_EXTENSION, STORAGE_SCHEMA_EXT}`
- **THEN** `plugin_manager.get_all(PluginType.NODE_EXTENSION)` 与 `get_all(PluginType.STORAGE_SCHEMA_EXT)` MUST 都能返回该插件

#### Scenario: 单接口插件默认行为

- **WHEN** 一个插件未覆写 `get_types()`
- **THEN** `get_types()` MUST 返回 `{get_type()}`

---

### Requirement: core 不依赖 interfaces（单向依赖）

依赖关系 SHALL 满足单向原则：`core` 不依赖 `interfaces`。`PluginManager` SHALL 仅依赖 `core/plugin.py`，按 `PluginType` 索引，不含任何按 interface 类的 `isinstance` 收集逻辑。

#### Scenario: core 不在运行时导入 interfaces

- **WHEN** 检查 `mcs/core/` 下所有 `.py` 文件
- **THEN** 非 TYPE_CHECKING 块内 MUST NOT 导入 `mcs.interfaces`

#### Scenario: PluginManager 无接口特化收集方法

- **WHEN** 检查 `core/plugin_manager.py`
- **THEN** MUST NOT 含 `collect_schema_extensions()` / `collect_node_extensions()` 等按 interface 类 `isinstance` 筛选的方法
- **AND** 此类收集 SHALL 由调用方用 `get_all(PluginType.X)` 完成

---

### Requirement: PluginContext 支持 StoreInterface

`PluginContext` SHALL hold a `store: StoreInterface` attribute instead of `graph: GraphStoreInterface`. This allows plugins to access the unified storage interface.

#### Scenario: PluginContext 持有 StoreInterface

- **WHEN** `PluginContext` 初始化
- **THEN** MUST 包含 `store: StoreInterface` 属性

#### Scenario: 插件通过 context.store 访问存储

- **WHEN** 插件通过 `context.store` 访问存储
- **THEN** 类型 MUST 为 `StoreInterface`

---

### Requirement: PluginManager 支持注销插件

`PluginManager` SHALL 提供 `unregister(name: str) -> bool` 方法，用于移除已注册的插件。

#### Scenario: unregister 成功移除插件

- **WHEN** 调用 `manager.unregister("existing_plugin")` 且该插件已注册
- **THEN** MUST 从 `manager._plugins` 中移除该插件
- **AND** MUST 从 `manager._by_type` 的所有相关类型列表中移除该插件
- **AND** MUST 返回 `True`

#### Scenario: unregister 插件不存在

- **WHEN** 调用 `manager.unregister("nonexistent")`
- **THEN** MUST 返回 `False`
- **AND** MUST NOT 抛出异常

---

### Requirement: MCS 支持定向插件注册与注销

`MCS` 类 SHALL 提供 `register_plugin(plugin, target)`、`register_shared_plugin(plugin)` 和 `unregister_plugin(name, target)` 方法，支持向指定管线注册和注销插件。

#### Scenario: register_plugin 指定目标管线

- **WHEN** 调用 `mcs.register_plugin(plugin, target="writer")`
- **THEN** 插件 MUST 只注册到 `write_manager`
- **AND** `read_manager.get_by_name(plugin.get_name())` MUST 返回 `None`

#### Scenario: register_shared_plugin 注册到两侧

- **WHEN** 调用 `mcs.register_shared_plugin(plugin)`
- **THEN** 插件 MUST 注册到 `write_manager` 和 `read_manager` 两侧
- **AND** 同一实例 MUST 在两个 manager 中可查

#### Scenario: unregister_plugin 从指定管线移除

- **WHEN** 调用 `mcs.unregister_plugin("plugin_name", target="reader")`
- **THEN** 只从 `read_manager` 移除插件
- **AND** 若同名插件存在于 `write_manager`，MUST NOT 受影响

---


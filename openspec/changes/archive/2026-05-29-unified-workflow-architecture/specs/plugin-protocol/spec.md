## ADDED Requirements

### Requirement: 提供 EntryPluginInterface 用于种子定位

The system SHALL define `EntryPluginInterface` with: a `priority: int` attribute, an `exclusive: bool` attribute (default False), and an abstract `locate(query: str, ctx) -> List[Node]` method.

#### Scenario: 接口最小契约

- **WHEN** 实现一个 EntryPlugin
- **THEN** 子类 MUST 提供 `priority`、`exclusive`、`locate` 三个成员；`locate` MUST 返回 `List[Node]`

#### Scenario: priority 决定合并顺序

- **WHEN** 框架合并多个 EntryPlugin 的输出
- **THEN** 合并结果 MUST 按 priority 降序排列；同 priority 的相对顺序未定义

#### Scenario: exclusive 短路语义

- **WHEN** 高优先级插件返回非空且 `exclusive=True`
- **THEN** 框架 MUST 不调用比它优先级低的 EntryPlugin

---

### Requirement: 提供 TrimPluginInterface 用于统一裁剪

The system SHALL define `TrimPluginInterface` with abstract method `trim(nodes: List[Node], budget: int) -> List[Node]`. This interface MUST be reusable at both stage ② (seed trimming) and as the underlying implementation of `PriorityArbitrationPlugin` at stage ④.

#### Scenario: trim 不破坏顺序语义

- **WHEN** TrimPlugin.trim 接收按优先级排序的 nodes 列表
- **THEN** 返回的子集 MUST 保持原顺序（不重排）

#### Scenario: trim 满足预算约束

- **WHEN** TrimPlugin.trim 完成
- **THEN** 返回 nodes 的估算 token 总和 MUST ≤ `budget`

#### Scenario: TrimPlugin 可挂载在多个位置

- **WHEN** 同一个 TrimPlugin 实例同时被读流程 ② 和（通过 PriorityArbitrationPlugin 包装后）④ 引用
- **THEN** 框架 MUST 允许此种复用，不要求每个挂载点持有独立实例

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

### Requirement: 提供 PostprocessPluginInterface 用于后置处理

The system SHALL define `PostprocessPluginInterface` with abstract method `process(input: Any, ctx) -> Any`. The interface MUST NOT constrain input/output type beyond being chainable.

#### Scenario: 输入输出类型自由

- **WHEN** 实现 PostprocessPlugin
- **THEN** 子类 MUST 能声明任意输入类型与任意输出类型；框架 MUST 不强制类型断言

#### Scenario: 多个 PostprocessPlugin 可串联

- **WHEN** 配置中注册多个 PostprocessPlugin
- **THEN** 框架 MUST 按注册顺序串行调用；前一个的输出作为后一个的输入

#### Scenario: 复用于读流程 ⑤ 和写流程 ①

- **WHEN** 同一个 PostprocessPlugin 类既作读后置也作写前置
- **THEN** 框架 MUST 允许同一个类的不同实例分别挂载在两处

---

### Requirement: 提供 CompactionPluginInterface 用于写流程压缩

The system SHALL define `CompactionPluginInterface` with: `should_run(changed_nodes, graph) -> bool` and `run(changed_nodes, graph, llm_caller) -> None`. Only plugins whose `should_run` returns True execute `run()`.

#### Scenario: should_run 短路 run

- **WHEN** 某 CompactionPlugin 的 should_run 返回 False
- **THEN** 框架 MUST 不调用该插件的 run

#### Scenario: run 可获得 LLM 调用句柄

- **WHEN** CompactionPlugin.run 被调用
- **THEN** 框架 MUST 传入 `llm_caller`（统一调用模式的入口）；插件可用它执行 `decide_hub` 等 purpose

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
- **THEN** 迁移路径 MUST 明确：幂等检查迁移到写前置 PostprocessPlugin；追加 source 迁移到 ⑤ 图更新后的压缩链或独立的 NodeExtension 钩子

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

For any plugin chain that supports priority (entry plugins, postprocess plugins), the system SHALL use the same semantics: descending priority order; tie-breaking unspecified; explicit `exclusive=True` on EntryPlugin short-circuits lower priorities; no implicit short-circuiting elsewhere.

#### Scenario: 同种插件链语义一致

- **WHEN** 实现 EntryPlugin chain 与 Postprocess chain
- **THEN** 两者 MUST 使用相同的排序规则（priority 降序）；MUST 仅 EntryPlugin 支持 `exclusive=True`（因为 Postprocess 是串联管道而非选择器）

#### Scenario: 同 priority 行为未定义但稳定

- **WHEN** 两个插件 priority 相同
- **THEN** 框架 MUST 在同一配置下产生相同的执行顺序；具体顺序由插件注册顺序决定（先注册者先执行）

---

### Requirement: PluginManager 支持新插件接口的注册与查找

`PluginManager` SHALL provide registration and lookup for all 5 new plugin interfaces (Entry, Trim, Arbitration, Postprocess, Compaction), and maintain priority-sorted lists for those that need ordering.

#### Scenario: 按接口类型查找

- **WHEN** `PluginManager.get_all(EntryPluginInterface)`
- **THEN** 返回值 MUST 是按 priority 降序排列的所有已注册 EntryPlugin

#### Scenario: ArbitrationPlugin 单例检查

- **WHEN** 注册第二个 ArbitrationPlugin
- **THEN** PluginManager MUST 在 `initialize_all` 或 `register` 时抛错

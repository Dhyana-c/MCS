## MODIFIED Requirements

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

## ADDED Requirements

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

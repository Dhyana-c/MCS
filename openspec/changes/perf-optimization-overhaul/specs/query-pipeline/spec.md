## MODIFIED Requirements

### Requirement: 入口插件链累积合并并按优先级排序

In stage ②, all registered `EntryPluginInterface` instances SHALL execute. Their outputs MUST be merged and sorted by plugin priority (descending). A plugin MAY declare `exclusive=True` to short-circuit lower-priority plugins on non-empty hit. Each plugin's `locate` call SHALL be independently wrapped in try/except; a single plugin failure MUST NOT prevent other plugins from executing.

#### Scenario: 多个入口插件全部执行

- **WHEN** 配置三个入口插件 A(priority=100)、B(priority=80)、C(priority=0)，A 和 B 都返回非空候选
- **THEN** 框架 MUST 把 A 和 B 的候选合并，按优先级排序后送入下一步（C 的执行取决于是否短路）

#### Scenario: exclusive 短路低优先级插件

- **WHEN** 高优先级插件 A 声明 `exclusive=True` 且返回非空候选
- **THEN** 框架 MUST 不调用比 A 优先级低的插件

#### Scenario: 全部入口插件返回空

- **WHEN** 所有入口插件（含 priority=0 的兜底）都返回空
- **THEN** 框架 MUST 返回空 `seeds`；后续 ③ Loop 立即终止；最终 `result_set` 为空

#### Scenario: 单插件异常隔离

- **WHEN** 入口插件 A（priority=100）的 `locate` 方法抛出异常
- **THEN** 框架 MUST 记录 WARNING 日志（含插件名和错误信息），继续执行后续入口插件 B/C；MUST NOT 让 A 的异常拖垮整次种子定位

#### Scenario: 所有插件异常时返回空

- **WHEN** 所有入口插件均抛出异常
- **THEN** 框架 MUST 返回空 `seeds`；后续遍历 MUST 自然终止；MUST 记录每次异常的 WARNING 日志

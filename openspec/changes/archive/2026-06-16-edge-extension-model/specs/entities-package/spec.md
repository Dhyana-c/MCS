## MODIFIED Requirements

### Requirement: 实体模块内容

The system SHALL expose the pure data models in `mcs.entities`. `Edge` SHALL gain an `extensions: dict[str, Any]` field (default empty dict), 与 `Node.extensions` 对称，供 `EdgeExtensionInterface` 插件挂载字段；其余实体字段不变。

#### Scenario: graph 模块导出图数据类

- **WHEN** 加载 `mcs.entities.graph`
- **THEN** 存在 `Node` dataclass（字段 `id, name, content, role, extensions`）、`Edge` dataclass（字段 `source_id, target_id, id, kind, label, priority, extensions`）、`Subgraph` dataclass（字段 `focus_id, nodes, edges`）

#### Scenario: Edge.extensions 默认空字典

- **WHEN** 不传 `extensions` 构造 `Edge`
- **THEN** `edge.extensions` MUST 为独立空字典（`default_factory=dict`，各实例不共享）

#### Scenario: decisions 模块导出管线数据类

- **WHEN** 加载 `mcs.entities.decisions`
- **THEN** 存在 `ConceptDraft`、`Decision`、`DecisionList`、`Community`、`MultiHubDecision`、`ActionType`

#### Scenario: config 模块导出配置与常量

- **WHEN** 加载 `mcs.entities.config`
- **THEN** 存在 `MCSConfig` dataclass 与常量 `PHASE1_SHARED_PLUGINS`、`PHASE1_WRITE_PLUGINS`、`PHASE1_READ_PLUGINS`、`PHASE1_DEFAULT_PLUGINS`

#### Scenario: 顶层包汇总 re-export

- **WHEN** 执行 `from mcs.entities import Node, Edge, Subgraph, MCSConfig`
- **THEN** 导入成功，无需指明子模块路径

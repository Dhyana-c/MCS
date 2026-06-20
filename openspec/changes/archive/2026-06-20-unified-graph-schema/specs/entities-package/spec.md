# entities-package（delta）

## MODIFIED Requirements

### Requirement: 实体模块内容

The system SHALL expose the pure data models in `mcs.entities`. `Edge` SHALL 以 `type`（**取代 `kind` + `label`**）承载结构 / 语义类别（当前仅 `关联` / `互斥`），保留 `priority`、`extensions`（`extensions` 与 `Node.extensions` 对称，供 `EdgeExtensionInterface` 插件挂字段）。`Node` SHALL 增 `node_class`（`概念` / `事实` / `事件` / `source`）作为节点分类轴；`hub` 降为标记（存于 `extensions`，不作为 role / 节点类）。

#### Scenario: graph 模块导出图数据类

- **WHEN** 加载 `mcs.entities.graph`
- **THEN** 存在 `Node` dataclass（字段 `id, name, content, node_class, extensions`）、`Edge` dataclass（字段 `source_id, target_id, id, type, priority, extensions`）、`Subgraph` dataclass（字段 `focus_id, nodes, edges`）
- **AND** `Edge` MUST NOT 有 `kind` / `label` 字段；`type` MUST ∈ 已登记类型（当前 `关联` / `互斥`）
- **AND** `Node` MUST NOT 以 `role` 作分类轴；`hub` MUST 仅为标记

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

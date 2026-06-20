# edge-extension-model Specification

## Purpose
TBD - created by archiving change edge-extension-model. Update Purpose after archive.
## Requirements
### Requirement: 边的可扩展字段模型

系统 SHALL 提供与节点对称的边扩展机制：`Edge` MUST 持有 `extensions: dict[str, Any]`（默认空字典），插件经 `EdgeExtensionInterface` 向其挂载字段。边扩展数据 MUST 随边对象**逐条保真**：SQLite 经 `extensions_json` 列编解码、内存 store 直接持有；**两端反查**（`get_relations`）返回的同一边对象 MUST 带完整 `extensions`；**重组**（fanout 合并迁移）与**快照 / 回滚** MUST 保真复制 `extensions`（独立 dict，不共享引用）。未挂任何边扩展时，写入 / 查询 / 渲染 / 守门行为 MUST 与本变更前**逐字一致**。

#### Scenario: 边持有扩展字段并保真

- **WHEN** 一个 `EdgeExtensionInterface` 插件（`get_name()="created_at"`）已注册，写入一条带该字段的边
- **THEN** 该边 `extensions["created_at"]` MUST 可写可读；持久化后重新加载 MUST 取回同值

#### Scenario: 扩展字段随反查可见

- **WHEN** 关联边连 A 与 B 带 `extensions["activity"]=3`，分别 `get_relations(A)` 与 `get_relations(B)`
- **THEN** 两端返回的边对象 MUST 都带 `extensions["activity"]==3`

#### Scenario: 重组保真

- **WHEN** fanout 合并把成员边迁移到代表节点（`_migrate_edges`）
- **THEN** 迁移后的边 MUST 带原边完整 `extensions`；MUST NOT 因重组丢失扩展字段

#### Scenario: 快照不共享引用

- **WHEN** `snapshot` 后修改某边的 `extensions`，再 `restore`
- **THEN** restore 出的边 `extensions` MUST 为快照时的独立副本（修改 MUST NOT 串味）

#### Scenario: 无边扩展时基线不变

- **WHEN** 未注册任何边扩展
- **THEN** 边的存取 / 渲染 / 守门 MUST 与本变更前逐字一致；`extensions` 为空字典、不产生额外存储或渲染

---

### Requirement: EdgeExtensionInterface 契约

系统 SHALL 定义 `EdgeExtensionInterface`，继承 `Plugin`，`get_type()` 返回 `PluginType.EDGE_EXTENSION`。它 MUST 提供抽象方法 `schema() -> dict`、`default() -> Any`、`serialize(data) -> dict`、`deserialize(data) -> Any`，并 MAY 提供可选 `render(edge, purpose) -> str | None`（默认返回 `None`）。`execute()` MUST 抛 `NotImplementedError`。插件 `get_name()` MUST 作为 `edge.extensions` 的键。

#### Scenario: 接口最小契约

- **WHEN** 实现一个 `EdgeExtensionInterface`
- **THEN** 子类 MUST 提供 `schema / default / serialize / deserialize`；`get_type()` MUST 返回 `PluginType.EDGE_EXTENSION`；`render` 未覆写时 MUST 返回 `None`

#### Scenario: 按类型查找边扩展

- **WHEN** 调用 `plugin_manager.get_all(PluginType.EDGE_EXTENSION)`
- **THEN** 返回值 MUST 是所有已注册的 `EDGE_EXTENSION` 类型插件

---

### Requirement: 字段级渲染可见性

边 / 节点的每个扩展字段 SHALL 自行决定在某 `purpose` 下是否渲染：`render(node/edge, purpose)` 返回片段=可见、返回 `None`=隐藏、MUST NOT 进入渲染文本。边渲染函数 MUST 接受 `purpose`（与 `extensions`）参数，使按 purpose 切换可见性可实现；`render_facts` MUST 把其 `purpose` 透传给边渲染。

本要求仅约束**渲染侧**。其与 token 估算的一致性按下条"边渲染 / 估算的查询侧一致性"处理；本要求 MUST NOT 被解读为要求修改守门估算（守门不渲染 / 不估算关系边，见 `plugin-protocol` 可见性契约与本变更 design D3）。

#### Scenario: 隐藏字段不渲染

- **WHEN** 边扩展 `created_at` 的 `render(edge, purpose)` 对所有 purpose 返回 `None`
- **THEN** 该字段 MUST NOT 出现在任何渲染文本中

#### Scenario: 不同 purpose 可见性不同

- **WHEN** 一个边扩展在 `purpose="select_facts"` 返回片段、在 `purpose="decide_hub"` 返回 `None`
- **THEN** 框架 MUST 仅在 `select_facts` 渲染时含该片段；边渲染函数 MUST 据传入的 `purpose` 做此区分

---

### Requirement: 边渲染 / 估算的查询侧一致性

边的 token 估算 SHALL 与边渲染**同口径**：估算函数 MUST 委托对应渲染函数取文本后估算（**MUST NOT** 为扩展字段另开估算公式 / 路径）；当渲染函数增 `extensions` / `purpose` 参时，估算函数 MUST 透传同参，使可见扩展片段在两侧一致。此一致性服务于**查询侧** token 计数正确性（`render_facts` 渲染事实给 LLM 的真实窗口；及 Phase 2 对查询视图按 `priority` 截断），**不涉及守门铁律一**（守门不估算关系边）。

#### Scenario: 估算委托渲染、含可见扩展

- **WHEN** 一条边带可见扩展片段（其 `render(edge, purpose)` 返回片段），在该 purpose 下被估算
- **THEN** 估算值 MUST 等于含该片段的实际渲染文本的 token 量（经委托渲染函数取得，非独立公式）

#### Scenario: 隐藏字段不计入

- **WHEN** 边扩展在该 purpose 下 `render` 返回 `None`
- **THEN** 该字段 MUST NOT 进入渲染，估算 MUST 与不带该字段时相等

---

### Requirement: 派生优先级（seam）

边的 `priority` 的**目标态** SHALL 为派生值——由 `PriorityScorer` 从边扩展字段计算、不作为写入方权威原语；此目标态在 **Phase 2** 于 store 层 chokepoint 接入 scorer 后兑现。**本期（Phase 1）仅引入 seam**：系统 MUST 提供默认 `PriorityScorer`，其 `score(edge) -> float` 返回当前默认值（`0.0`）、使行为**零变化**，并在文档声明 priority 的目标语义。Phase 1 MUST NOT 改写路径——`add_edge` / `Edge.__init__` 的 `priority` 参数、`_migrate_edges` 的 priority 保真复制**保持现状**（priority 此期仍为 `0.0` 存储值；**不标 deprecated**——其替代 chokepoint 尚未存在，过早 deprecate 会误导）。存储 `edges.priority` 列 MAY 作（Phase 2）派生值缓存。

#### Scenario: Phase 1 默认打分器零行为变化

- **WHEN** 使用默认打分器
- **THEN** `score(edge)` MUST 返回 `0.0`；写入边后其 `priority` MUST 仍为 `0.0`（与本变更前一致）；排序 / 截断行为 MUST 不变

#### Scenario: priority 目标语义仅文档声明、Phase 1 不改写路径

- **WHEN** 审查 `priority` 的定义与 Phase 1 代码
- **THEN** 文档 MUST 声明目标态权威来源为"扩展字段 + 打分器"、存储列为缓存；Phase 1 代码 MUST NOT 在写路径接入 scorer、MUST NOT 标记 `priority` 参数为 deprecated（仅留 seam，目标态 Phase 2 兑现）


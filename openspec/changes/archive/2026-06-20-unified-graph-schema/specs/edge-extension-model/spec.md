# edge-extension-model（delta）

> 边扩展机制（`extensions` 字典、逐条保真、重组 / 快照保真复制）本身不变；仅把反查方法名 `get_facts` / `get_assoc` 统一为 `get_relations`，示例边去 `label`。

## MODIFIED Requirements

### Requirement: 边的可扩展字段模型

系统 SHALL 提供与节点对称的边扩展机制：`Edge` MUST 持有 `extensions: dict[str, Any]`（默认空字典），插件经 `EdgeExtensionInterface` 向其挂载字段。边扩展数据 MUST 随边对象**逐条保真**：SQLite 经 `extensions_json` 列编解码、内存 store 直接持有；**两端反查**（`get_relations`）返回的同一边对象 MUST 带完整 `extensions`；**重组**（fanout 合并迁移）与**快照 / 回滚** MUST 保真复制 `extensions`（独立 dict，不共享引用）。未挂任何边扩展时，写入 / 查询 / 渲染 / 守门行为 MUST 与本变更前**逐字一致**。

#### Scenario: 两端反查带完整 extensions

- **WHEN** 关联边连 A 与 B 带 `extensions["activity"]=3`，分别 `get_relations(A)` 与 `get_relations(B)`
- **THEN** 两次返回的同一边对象 MUST 都带 `extensions["activity"]=3`

#### Scenario: 重组与快照保真复制

- **WHEN** 边经 fanout 重组迁移、或图快照 / 回滚
- **THEN** 其 `extensions` MUST 被保真复制为独立 dict（不共享引用）

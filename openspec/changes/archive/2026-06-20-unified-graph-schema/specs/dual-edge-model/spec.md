# dual-edge-model（delta：整体移除）

> 本 change 以**谓词落点（事实即节点）+ 边仅 `关联`/`互斥` + 层级由聚类涌现**取代双边模型。`property_graph` 的带 label 事实边、`kind=hierarchy/fact` 全部不再存在，故 `dual-edge-model` 的全部 requirement 移除。承接：关系语义见 `unified-graph-schema`，边/节点字段见 `entities-package`，有界与 priority 截断见 `subgraph-bounding`。

## REMOVED Requirements

### Requirement: 全图两类边——层级边与事实边

**原因**：取消 `kind`（hierarchy / fact）与 label 事实边。关系改为**命题节点**（谓词落 `content`）；层级由聚类涌现（关联边 + `hub` 标记，非独立边类型）；边仅保留 `关联` / `互斥`。

### Requirement: 事实边存一份、两端可达（反查）

**原因**：事实不再是边。"只存一份、两端可达、反查"语义转移到 `关联` 边（见 `unified-graph-schema` / `entities-package`）。

### Requirement: 事实边带 priority（为遗忘预留）

**原因**：`priority` 改挂在 `关联` 边 / 节点（用于入边·关联截断与遗忘），不再绑定"事实边"；"任何阶段不建溢出索引"的不变量由 `subgraph-bounding` 承载。

### Requirement: content 精简，关系上事实边，属性升格

**原因**：关系语义改由命题节点承载，不再"上事实边"；节点 `content` 口径见 `unified-graph-schema` 与 `docs/graph-model-design.md`。

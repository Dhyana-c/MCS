# attribute-node-model（delta：整体移除）

> 统一为单一模型后，不再有可切换的"第二种关系表示模式"。本能力的机制（属性 / 命题节点 + 无类型关联边 + 渲染估算口径）作为**底座并入 `unified-graph-schema`**（关联边、谓词落点、估算 == 渲染），`relation_model` 开关删除。故 `attribute-node-model` 全部 requirement 移除。

## REMOVED Requirements

### Requirement: relation_model 模式开关

**原因**：单一模型，删除 `MCSConfig.relation_model` 开关与 `property_graph`/`attribute_node` 双模式（爆炸半径见 proposal）。

### Requirement: 无类型关联边 kind="assoc"

**原因**：无类型关联边升为统一模型的基础边 `关联`（`type="关联"`，取代 `kind="assoc"`）；两端可达 / 去重语义并入 `unified-graph-schema` 与 `entities-package`。

### Requirement: 关系具体化为属性节点（不带版本）

**原因**：关系具体化为节点的思路升为统一模型的**事实（命题）节点**（谓词落 `content`），并入 `unified-graph-schema`。

### Requirement: attribute_node 模式写入产属性节点 + 无类型边

**原因**：不再是"某模式下"的写入分支；统一写入流程见 `unified-graph-schema` / `write-pipeline`（规则入库 + 复用 read 对齐 + 连关联边）。

### Requirement: attribute_node 模式查询遍历无类型边与属性节点

**原因**：不再分模式；统一查询沿 `关联` 边做核心 BFS，见 `unified-graph-schema` / `query-pipeline`。

### Requirement: attribute_node 模式渲染与估算口径（铁律一）

**原因**：估算 == 渲染（含关联边、`type` 不计 token）并入 `unified-graph-schema` 与 `subgraph-bounding`，不再随模式切换口径。

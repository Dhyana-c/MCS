## Context

MCS 要作为框架交付（依赖库 / 未来 MCP），允许用户"在框架下扩展"。节点扩展已成熟（`Node.extensions` + `NodeExtensionInterface`，含 `render(node, purpose)` 可见性，`nodes` 表已有 `extensions_json`）；插件与 prompt 覆盖也都已有。**唯独边不可扩展**：`Edge` 固定数据类、`edges` 表无扩展列、存储 schema 扩展只管 `nodes`。另两件配套：`priority` 现为存储原语（应改派生）、库不记录建库出处（打包后易混库静默损坏）。

采 **A 方案**：节点 / 边定制 = 加字段；核心语义由 prompt 控制（`decide_hub` 等已可覆盖），框架攥死"何时裂变 / 截断"那条不变量。

**两次独立 review 的关键校正（已纳入本设计）**：守门器（铁律一实际执行者）只渲染节点层级视图、**不估算关系边**（[fanout_reducer.py:395](mcs/plugins/maintenance/fanout_reducer.py:395)），且 `estimate_active_view / estimate_*_edge` 当前**零调用方**。故"边扩展计入估算 → 铁律一"是**论证错位**：边渲染 / 估算属**查询侧** token 计数正确性，与守门铁律一无关。本设计据此把两者拆开，**不修改守门 / subgraph-bounding**。

关键模块：`Edge`（`entities/graph.py`）、`PluginType`（`core/plugin.py`）、新增 `interfaces/edge_extension.py`、`ContextRenderer` / `TokenBudget`、`StoreInterface` 及两 store、`FanoutReducerPlugin`、`presets` / `builder`。

## Goals / Non-Goals

**Goals**
- 边获得与节点对称的扩展字段机制（`EdgeExtensionInterface` + `Edge.extensions` + 存储 / 反查 / 重组 / 快照保真）。
- 字段级渲染可见性：`render(node/edge, purpose)→None` = 隐藏、不渲染；边渲染函数补 `purpose` 参以支持按 purpose 切换。
- `priority` 改为可派生（`PriorityScorer` seam），Phase 1 默认 `0.0`、零行为变化。
- 库记录建库出处；开库 `relation_model` 不一致拒绝、扩展集变化告警；旧库附加列补齐确保可写。
- `property_graph` 基线回归**逐字不变**；**守门 / 铁律一不变**。

**Non-Goals（本期不做）**
- MCP 适配层、配置文件加载、插件自动发现、注册新 purpose。
- 阶段 2 真实衰减 / 活跃 / 遗忘打分逻辑、派生优先级的**写路径接线**（仅引入 seam + 默认）。
- 新结构角色 / 用户可改核心图行为（A 方案否决 B）。
- 节点侧 `priority`；旧库**数据 / `relation_model`** 迁移（附加列补齐除外）。
- 修改守门估算 / 让节点扩展计入估算（保持 `estimate_node(extensions=None)` 现状）。

## Decisions

### D1：新增 `EdgeExtensionInterface` + `PluginType.EDGE_EXTENSION`

- 镜像 `NodeExtensionInterface`：`schema() / default() / serialize() / deserialize()` + 可选 `render(edge, purpose) -> str | None`（默认 `None`）。插件 `get_name()` 作 `edge.extensions` 的键。
- 新增 `PluginType.EDGE_EXTENSION`；`ContextRenderer` 渲染边时查 `get_all(PluginType.EDGE_EXTENSION)`。
- **备选**：复用 `NODE_EXTENSION` 同时处理点边。**否决**——点 / 边是不同实体，渲染派发与 `schema` 归属会混淆；分类型派发干净、与按类型索引一致。

### D2：`Edge.extensions` 与存储 / 重组保真

- `Edge` 增 `extensions: dict[str, Any] = field(default_factory=dict)`，与 `Node` 对称。
- SQLite：`edges` 表增 `extensions_json TEXT` 列，编解码复用 `nodes` 的保真路径（`_node_extensions` 同构出 `_edge_extensions`）；`save_full` / `load` 逐条保真。`InMemoryStore` 直接持有对象。
- **反查不受影响**：`extensions` 跟边对象走，`get_facts` / `get_assoc` 两端索引返回同一边对象。
- **重组保真**：`FanoutReducerPlugin._migrate_edges` 现以 `kind/label/priority` 重建边（[fanout_reducer.py:690](mcs/plugins/maintenance/fanout_reducer.py:690)），MUST 增 `extensions=edge.extensions`，否则合并迁移丢扩展数据。`store.add_edge` 相应增 `extensions` 参。
- **快照保真**：`snapshot` 对节点已深拷 `extensions=dict(n.extensions)`，对边只 `dc_replace(e)`（in_memory.py:293 / sqlite_store.py:343）；边有 `extensions` 后 MUST 同样深拷 `extensions=dict(e.extensions)`，否则 restore 后字典引用共享、改动串味。
- 边扩展走 `extensions_json` 单列（与节点同构），**不**为每字段建独立列。需可查询列 / 索引的高级场景留待后续单独提（**本期不动 `StorageSchemaExtensionInterface`**——给它加 `edge_columns()` 既无用、又会破坏既有实现）。
- **备选**：边字段一律建独立 SQL 列 / 本期就加 `edge_columns()`。**否决**——多数 Phase 2 字段是后台元数据，json 列足够零摩擦；接口扩展属范围蔓延。

### D3：字段级可见性（渲染侧）+ 边渲染 / 估算的正确定位

- 可见性挂在每个扩展上：`render(node/edge, purpose)` 返回片段=可见、`None`=隐藏、不进渲染文本。
- 边渲染函数 `render_fact_edge` / `render_assoc_edge` 现**无 `purpose` 参**，MUST 同时增 `extensions` 与 `purpose` 两参；`render_facts`（[context_renderer.py:136](mcs/core/context_renderer.py:136) 已有 purpose）透传。无 `purpose` 则 `ext.render(edge, purpose)` 无法按 purpose 切换（review C）。
- **签名默认 + 死代码处置**：`purpose` 取安全默认 `"select_facts"`、`extensions` 默认 `None`。死代码 `estimate_active_view`（零调用方）内部 `est_edge(edge, node_map)` 凭默认继续可用——**本期不删不改**。否决"删除"（review 备选）：它可能被 token-budget 相关 spec/test 引用、且是 Phase 2 查询视图截断的预期入口，删了 Phase 2 还要重建；默认参已彻底消除"Phase 2 需适配签名"的顾虑，比删除更低风险。
- **守门铁律一与边无关，不修改**：守门只估算节点层级视图（`render([node, *neighbors], "decide_hub")`），不渲染 / 不估算关系边；节点扩展在守门估算中本就不计（`estimate_node(extensions=None)`）。本变更**不动** `estimate_node` / 守门口径 / `subgraph-bounding`。
- **边渲染 == 边估算属查询侧正确性**：`render_facts`（[query_engine.py:312](mcs/core/query_engine.py:312) / [:393](mcs/core/query_engine.py:393)）把事实渲染给 LLM——可见边扩展应显示在该次 LLM 调用窗口内。`estimate_fact_edge` / `estimate_assoc_edge` 已委托对应 `render_*_edge`（单一渲染口径），**当前零调用方**；待 Phase 2 对查询视图按 priority 截断时，凭此委托保持渲染 == 估算。本期保证：边渲染函数加扩展 / purpose 后，估算函数随之透传同参（不另开估算公式），为 Phase 2 留正确接缝。
- **备选**：给边扩展单开 token 估算路径。**否决**——渲染一处、估算一处是历史漂移坑（破坏一致性）；唯一渲染函数委托是硬约束。

### D4：派生优先级（seam，Phase 1 不接线）

- `priority` 定义为派生值：由 `PriorityScorer.score(edge) -> float` 从 `edge.extensions`（创建时间、活跃数等）算，**非写入方权威原语**。
- **chokepoint 在 store 层 `Edge` 创建处**，不在 `write_pipeline`——经核实 `write_pipeline` 所有 `add_edge` 都不传 priority（用默认 `0.0`），唯一来源是 `store.add_edge(priority=0.0)` 默认参 + `Edge.__init__`；唯一显式赋值是 `_migrate_edges` 的保真复制。
- **Phase 1 只引入 seam，不接写路径**：新增 `PriorityScorer` 接口 + 默认实现（`score` 返回 `0.0`，零行为变化）+ 文档声明"priority 派生、非权威"。真正在 store chokepoint 调 scorer、真实衰减打分，留 Phase 2（届时配合活跃数 / 创建时间字段）。
- **"派生 / 非权威"是目标态、非 Phase 1 既成事实**：spec 把该 MUST 限定为目标态、Phase 2 兑现；`add_edge` / `Edge` 的 `priority` 参数本期**不标 deprecated**——替代（chokepoint 接 scorer）尚不存在，过早 deprecate 会误导（否决 review 备选"Phase 1 标 deprecated"）。这样 spec 声明与 Phase 1 代码一致、不互打脸。
- 存储 `edges.priority` 列保留为派生值缓存。`_migrate_edges` 重组复制：`extensions` 保真复制；`priority` 暂仍复制（Phase 2 改为经 scorer 重算）。
- 是否升格为 `PluginType.PRIORITY_SCORER` 留 Phase 2 按需，本期 builder 注入单一默认实现即可、不引入新插件类型。
- **备选 1**：本期就在 store chokepoint 接 scorer。**否决**——Phase 1 无可派生字段（活跃数 / 创建时间是 Phase 2 才挂），接了也只能返回 `0.0`，徒增写路径改动面与回归风险。
- **备选 2**：直接删 `priority` 列即时算。**否决**——Phase 2 批量排序 / 截断需快速读，缓存有用；删列动 schema 更大。

### D5：库出处记录 + 旧库附加列补齐

- 新增元表 `meta(key TEXT PRIMARY KEY, value TEXT)`，存 `relation_model`、`schema_version`、`extensions`（已挂点 / 边扩展名集，排序序列化，**仅作告警依据**）。
- **开库校验三态**：
  - `relation_model` **不一致** → MUST 拒绝（抛配置类错误）。这是唯一硬拒条件（宪法：混库未定义行为）。
  - `extensions` 集**变化** → 只记 WARNING、放行。理由：opt-in 读插件（rerank / semantic_trim）本就时挂时不挂；给旧库新增 / 移除扩展是合法迁移（新字段取默认、旧 orphan 字段被忽略），硬拒会误杀正常工作流（review 我方发现）。
  - **缺失**（旧库无 `meta`）→ 视为 legacy，按当前配置补写 `meta` + WARNING、放行。
- **旧库附加列补齐（让"放行"安全）**：`CREATE TABLE IF NOT EXISTS` 对既存 `edges` 表是 no-op、不会加 `extensions_json` 列（review E）。开库 MUST 检测列存在性（`PRAGMA table_info(edges)`），缺则 `ALTER TABLE edges ADD COLUMN extensions_json TEXT`（附加列、SQLite 下 O(1) 元数据操作、安全）。否则"补 meta 放行"会放行一个 INSERT 即抛 `OperationalError` 的库。
- 校验 + 补列 MUST 在 store `initialize` / builder 装配点完成，**先于任何读写**。`InMemoryStore` 无持久化，provenance / 补列均 no-op。
- **备选**：用 `PRAGMA user_version`（一个 int）。**否决**——装不下扩展集与模式串。

### D6：核心行为仍由 prompt 控制（A 方案，记录否决 B）

- 不新增"行为开关"，不暴露 `in_fanout` / `is_skeleton` / `token_side` / `orphan_via` 等不变量相关旋钮。
- 核心语义定制走既有 `prompt_overrides` / `register_prompt`（`decide_hub` 等已在可覆盖清单），**无需本变更新增机制**。
- **否决 B 方案**（用户定义新结构角色 / 改图行为）：直接动核心有界不变量，等于把炸毁框架核心价值的开关交给用户。框架攥死"何时"，prompt 管"如何"。

### D7：MCP / 打包入口本期不做（记录理由）

- 配置文件加载、插件自动发现、新 purpose 注册——架构已留缝（配置按名引用、`MCSBuilder.get_plugin_class` 单一解析点、prompt 按 purpose 覆盖），真打包时换 / 加这一处即可，现在做是投机式通用化。
- 本期唯一与打包真正交叉、且现在做便宜 / 以后补痛的是 **provenance + 附加列补齐**（D5）——且与"给边建表"同处改动，顺手做。

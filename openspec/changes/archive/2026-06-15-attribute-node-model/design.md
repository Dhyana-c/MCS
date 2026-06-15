## Context

`dual-edge-model` 把关系语义硬绑到带 label 的事实边（`主 —谓→ 宾`），并写进了宪法「边方向」与铁律一（估算口径含事实边 label token）。但 `docs/technical-design.md §2.2` 论证过另一模型——**无类型邻接边 + 属性节点**：边只表"相关"，关系具体化为属性节点上的自然语言说法。`Node.role="attribute"` 字段已预留、`decisions.attach_statement` action 仍在（已废弃为 no-op），都是这条旧设计的残骸。

本变更把"关系如何表示"做成**可切换模式**，将旧设计作为 **Phase 1 选项**复活（不含版本化）。关键约束：**默认模式（`property_graph`）行为逐字不变**——新模式是并行分支，不削弱既有不变量，只是把对 label 事实边的硬约束**限定到 `property_graph` 模式**。

关键模块：`Edge`/`Node`（`core/graph.py`）、`MCSConfig`（`core/config.py`）、`WritePipeline._apply_decisions`、`QueryEngine._node_view/_traverse`、`ContextRenderer`/`TokenBudget`、`StoreInterface` 及两个 store 实现、`judge_relations` prompt、`FanoutReducerPlugin`。

## Goals / Non-Goals

**Goals**
- 新增 `relation_model` 模式开关，`property_graph`（默认）与 `attribute_node` 并存、按 MCS 实例选定。
- `attribute_node` 模式：无类型关联边 `kind="assoc"` + 属性节点（`role="attribute"`，content 持单一当前说法）承载关系；全链路（写入 / 查询 / 渲染 / 估算 / 守门 / 存储）按模式分支。
- 铁律一（估算==渲染）在**每种模式内**逐字成立——口径随模式切换。
- `property_graph` 基线回归**零变化**。

**Non-Goals（本期不做）**
- 版本列表 / superseded / 出处 / 置信 / 事件层 / GC（Phase 2）。
- 两模式**同库混用**（一个 DB 一种模式）。
- 已有 `property_graph` 库**自动迁移**到 `attribute_node`。
- 不动 fanout 的铁律二（归纳仍 `decide_hub` 语义）。
- 不引入第三方三元组/RDF 后端（那是另一变更）。

## Decisions

### D1：模式开关 `relation_model`

- `MCSConfig` 新增 `relation_model: str = "property_graph"`，取值 `"property_graph"` | `"attribute_node"`；`knowledge_graph()` 预设默认 `property_graph`，另加 `knowledge_graph_attr()`（或参数 `relation_model=`）暴露新模式。
- **选定时机 = 建图时**，写入与查询 MUST 用同一模式；混库为未定义行为（不做运行期校验外的兜底）。
- 模式由 core 在分支点显式读取（见 D4/D5/D6），**不做成插件**——关系表示横切写入④⑤、渲染、遍历三处 core，无干净的单一插件点；强行插件化会割裂 core 控制流。prompt 选择复用既有 `prompt_overrides` 机制（按模式选模板）。

**备选**：复用现有 `mode`（knowledge_graph/memory_system）。否决——那是 Phase 轴（插件集），与关系表示轴正交，复用会耦合两个独立维度。

### D2：无类型关联边 `kind="assoc"`

- `Edge.kind` 增第三取值 `"assoc"`：**无 label**（`label` MUST 空串）、表"两概念相关/共现"，不表"怎么相关"。
- **两端可达**（反查）：与事实边一致，一条 assoc 边两端邻接都索引到它。store 新增 `get_assoc(node_id)` 返回该节点作任一端的 assoc 边。
- 内存索引复用 `_fact_by_node` 同构的两端索引（新增 `_assoc_by_node`，或在 `add_edge`/`_remove_edge_by_id` 按 `kind in {"fact","assoc"}` 走两端索引分支）；SQLite 边表 `kind` 列放开取值 `assoc`，`save_full`/`load` 逐条保真。
- **去重**：同一对节点的 assoc 边只存一份（无 label 可比，按 (source,target) 去重）。

**备选**：复用 `kind="fact"` + 空 label 表"无类型"。否决——宪法/spec 现有"事实边 label MUST 非空"，空 label fact 会污染 property_graph 模式的校验与渲染；新 kind 干净隔离。

### D3：属性节点（reified relation node）

- 关系具体化为**属性节点** R：`role="attribute"`，`name` = 关系的短名（如"小明的爱好"），`content` = **单一当前**自然语言说法（**无版本列表**；说法 MUST 简短、受长度上限约束，量级同 property_graph lean 基线，过长则压缩——否则关系侧视图无界，见 A2 / `subgraph-bounding`）。
- **结构（粒度默认）**：R 经 assoc 边连到该关系涉及的**每个概念端点**；纯字面值（不值得建节点的值，如"颜色:红"中的"红"）内联进 R.content。
  - 概念–概念关系 `A rel B`：建 R，`A —assoc— R`、`R —assoc— B`（A、B 两侧反查都能到 R，再到对端）→ 3 节点 + 2 assoc 边。
  - 概念–字面值 `A 属性=值`：建 R（content 含值），`A —assoc— R` → 2 节点 + 1 assoc 边。
- 属性节点对 LLM **同构于普通概念**（渲染为 name+content，无特殊标记）；`role="attribute"` 仅供系统识别/可观测。

### D4：写入链路（按模式分支）

- 阶段④ `judge_relations`：`attribute_node` 模式走**专属 prompt**（不产 label；产"为关系建属性节点 + 连无类型边"的意图）。实现走 prompt_overrides 按模式注入模板/parser，或 write_pipeline 按模式选 purpose。
- 决策：**复活并重定义 `attach_statement`**（现 no-op）为"建/并属性节点 + 连 assoc 边"，或新增 `create_attribute` action。`Decision` 增字段表达"属性节点 name/content + 端点列表"（端点用 id 或同批 name，沿用 `edges_to`/`edges_to_names` 的 id/name 双轨解析，但**去 label**）。
- 阶段⑤ `_apply_decisions`：`attribute_node` 模式分支——建属性节点、连 assoc 边（`add_edge(kind="assoc")`）；`property_graph` 分支保持现状（建 fact 边）。两分支共用同名去重/篇内 name 解析骨架。

### D5：渲染 / 估算口径（随模式，铁律一）

- `attribute_node` 模式：
  - 属性节点按**节点**渲染（name+content，走现有 `render_node_full`）——它就是关系的载体。
  - assoc 边渲染 `主 — 宾`（**无 label**，破折号邻接）；新增 `render_assoc_edge`。
  - `render_facts` 在该模式平铺 {节点（含属性节点）+ assoc 边} 为统一编号条目（与 property_graph 的 {节点 + fact 边} 对称）。
- **渲染器如何知道模式（B2）**：`ContextRenderer` 不持 `relation_model`，且有多处构造点（`query_engine.py:271` 局部构造、`fanout_reducer` 经 PluginContext 注入）。决定让 `render_facts`（及内部分发 `render_fact_edge` / `render_assoc_edge`）**收 `mode` 参数、由调用方传**——query_engine 持 config 可传，fanout 不渲关系边——避免改所有构造点与注入链。
- 估算：`TokenBudget` 估 assoc 边走 `render_assoc_edge`（无 label，比 fact 短）；活跃视图估算在该模式计 assoc 边 token、**不计** label fact token。**估算 MUST 复用渲染函数**——铁律一在该模式内逐字成立。
- **无新增重复计数风险（B1 澄清）**：property_graph 现状即把关系端点既渲为节点条目、又出现在 `主—label→宾` 边行，估算与渲染共用 `render_facts` 故估==渲恒成立；attribute_node 同构（属性节点既作节点条目、其名又出现在 `主—宾` 边行），一样恒成立，非新增问题。`token_budget.estimate_active_view` 当前**仅测试调用**、不在 Phase 1 关键路径（遍历走 `render_facts`+`estimate`）；Phase 2 启用其截断时再补 assoc 分支。控关系侧视图大小的真正抓手是**属性节点 content 须短**（见 D3 / `attribute-node-model`）。

### D6：查询遍历（事实 BFS 在 attribute_node 模式）

- `_node_view`：`attribute_node` 模式取 `get_out_hierarchy` + `get_assoc`（替代 `get_facts`）；assoc 边端点（含属性节点）补入视图。
- `_traverse`/`render_facts`/`select_facts`：机制不变（分层打包、批量+逐节点回退、编号选择、端点补入），仅"事实条目"来源从 fact 边换成 assoc 边、关系语义从 label 换成属性节点 content。
- **entity-anchored 仍成立**：从实体反查 assoc 命中属性节点，读其 content 得关系；极性/否定仍由 LLM 在属性节点说法上现推。
- 实现走 `config.relation_model` 显式分支；可加 store 便捷方法 `get_relations(node_id)`（property→fact、attribute→assoc）减少 query_engine 分支面（design 允许，tasks 定）。

### D7：守门 / fanout / root 维护（attribute_node 模式）

- **root 孤儿判定（A1，必修）**：`_maintain_seed_root`（`mcs/plugins/maintenance/fanout_reducer.py:284`）现以 `get_facts(n) 为空` 判孤儿、挂 root。`attribute_node` 模式关系走 assoc、`get_facts` 恒空 → **全部概念被判孤儿挂 root**，复现宪法反例的"`__seed_root__` 扁平直挂上千概念、破坏不变量"。故该模式下孤儿判定 MUST 改用 `get_assoc`（无 assoc 关联才算孤儿），等价口径 = `get_facts(n) ∪ get_assoc(n)` 皆空才挂 root。
- 守门口径（`decide_hub` 可行性）**仍只看层级出边侧**（中心 content + `get_out_hierarchy` 子节点），**不含 assoc/fact token**——与现状一致（铁律一守门口径条款不变）。
- **属性节点不在层级骨架（B3 修正）**：属性节点经 assoc（非 hierarchy）连实体，`get_out_hierarchy(属性节点)` 为空 → 它**不进任何节点的层级邻域、不参与 fanout 收敛**；其 token 与 assoc 边同属**关系侧**，由 Phase 2 截断兜（Phase 1 靠窗口余量），与 `subgraph-bounding` 一致。（先前"属性节点作普通子节点参与 fanout"措辞作废。）
- **fanout 边操作已正确（C2，验证非新增）**：`_absorb_hub_edges` 只处理 `kind=="hierarchy"`（[fanout_reducer.py:337](mcs/plugins/maintenance/fanout_reducer.py:337)，assoc 不被吸收）、`_migrate_edges` 已 `kind=edge.kind` 保真（:686）、`_rollback_reorg` 经 `store.restore` 快照还原——assoc 天然不受波及。任务降为**验证**：① assoc 去重（label 恒空、同对一条）正确；② 若 store 用独立 `_assoc_by_node` 索引，`snapshot/restore` MUST 一并捕获该索引（否则回滚丢 assoc 反查）。

### D8：存储（assoc 边索引与隔离）

- **sqlite schema 零改（C4 修正）**：边表 `kind TEXT NOT NULL DEFAULT 'hierarchy'` **无 CHECK 约束**，本就接受任意 kind 串——"放开取值"措辞作废，schema 迁移零成本。
- **真正的活在索引二分**：`in_memory.add_edge` 现为 `if kind=="hierarchy" … else（当 fact、入 _fact_by_node）`（[in_memory.py:135](mcs/stores/in_memory.py:135)），assoc 会落入 else 被当 fact；且 `get_facts` 不按 kind 过滤会**把 assoc 当事实返回**。故 MUST：① `add_edge` 改 kind **三分**（hierarchy / fact / assoc）；② assoc 两端索引——共用 `_fact_by_node` 则 `get_facts` / `get_assoc` **MUST 按 kind 过滤隔离**，或用独立 `_assoc_by_node`；③ assoc 去重按 `(source, target)`（label 恒空）；④ `delete_node` / `_remove_edge_by_id` / `snapshot` / `restore` 覆盖 assoc（独立索引时 snapshot MUST 捕获）。sqlite 的 `kind=="hierarchy"` 二分索引逻辑同理改三分。
- 无需数据迁移（新模式建新库）。

### D9：宪法修订（提议，未应用）

本变更**提议**把 `CLAUDE.md`：

- 「边方向」从"全图**两类**边"→"关系表示**可插拔**：`property_graph` 模式为层级边 + 带 label 事实边（现状）；`attribute_node` 模式为层级边 + 无类型关联边 + 属性节点。默认 `property_graph`。
- 「核心不变量 / 铁律一」措辞放宽为"活跃视图渲染口径**随 `relation_model`**；估算与渲染在每种模式内逐字一致（含该模式的关系边 token）"——硬约束不削弱，仅参数化。

按"变更若冲突，先改宪法（经评审）再改代码"：proposal 评审通过即视为宪法修订获批，**先落 `CLAUDE.md` 正文、再实现模式分支代码**，archive 仅最终校对。

## Risks / Trade-offs

- **[风险] 节点/边膨胀**：每条概念–概念关系 = +1 属性节点 + 2 assoc 边（vs 1 label 边）→ 节点数与 fanout 压力上升。接受；属性节点参与 fanout 归纳兜底，规模影响留评测量化。
- **[风险] 召回退化**：dual-edge 当初正是因"关系叙述进 content 腰斩召回"才取代旧模型。属性节点把说法移出实体 content（不同于"塞进实体 content"），理论上无此退化，但**MUST 评测对比**（multihop_rag 子集，attribute_node vs property_graph）。
- **[权衡] 两套链路维护成本**：用模式分支隔离、基线零变化、共用骨架（去重/解析/打包/回退）控制重复。
- **[权衡] 关系无 label → 检索靠属性节点 content + LLM**：entity-anchored 反查仍可达；同义谓词归一化问题被回避（旧设计的卖点）。
- **[风险] 模式误配（写一种读另一种）** → 同库单模式约定 + 建图时记录模式；越界为未定义行为。

## Spec 权责（单一真相源）

| 范围 | 权威 spec | 其余 spec 的角色 |
|---|---|---|
| 新模式总览（开关 / assoc 边 / 属性节点 / 全链路语义）| `attribute-node-model` | 其余 spec 引用 |
| label 事实边模型（限定到 property_graph 模式）| `dual-edge-model` | `store-interface` 复述 |
| 活跃视图口径随模式 / 铁律一参数化 | `subgraph-bounding` | 其余引用 |
| 写入④⑤模式分支 | `write-pipeline` | 细节以 `attribute-node-model` 为准 |
| 查询事实 BFS 模式分支 | `query-pipeline` | 细节以 `attribute-node-model` 为准 |
| 存储 API（`assoc` 边 / `get_assoc` / schema）| `store-interface` | — |
| prompt 选择 / 渲染随模式 | `llm-interaction` | — |

**修改规则**：动模式语义 / 边模型 / 不变量口径时，**先改 `attribute-node-model` 或对应权威 spec，再核对复述方**。

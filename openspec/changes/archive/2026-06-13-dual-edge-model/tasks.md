## 1. 核心模型与存储层

- [x] 1.1 `Edge` 增 **`id`（str，新增时自动 uuid）**、`kind`（`"hierarchy"` | `"fact"`）、`label`、`priority` 字段（`mcs/core/graph.py`）；边以 `id` 为主键、可寻址（支持 `delete_edge(id)` / `update_edge(id)`）；`Subgraph` 复用既有定义
- [x] 1.2 `StoreInterface`：事实边**存一份、两端索引**；新增 `get_facts(node_id)`（该节点作任一端的事实边、反查）、`get_out_hierarchy(node_id)`（层级出边）、`get_out_facts(node_id)`（出事实）、`get_edges_between(src,tgt)`；**`get_neighbors` / `get_out_neighbors` / `get_edge` / `add_bidirectional` 退役**（deprecated wrapper）（`mcs/core/store.py`）
- [x] 1.3 反查：`get_facts` MUST 返回该节点为**源或宾**的全部事实边（双向可达）
- [x] 1.4 `Edge.priority` 字段持久化（Phase 1 仅留字段、**不参与排序 / 截断**；priority 排序 + 渲染截断为 Phase 2）
- [x] 1.5 `InMemoryStore` / `SQLiteStore` 适配新 schema（`id`/`kind`/`label`/`priority` 列 + 索引；`_edges` 改 edge_id 主键；`_hierarchy_out` + `_fact_by_node` 双索引）；编写 rebuild 工具
- [x] 1.6 砍掉初版"降级不删除"相关代码路径
- [x] 1.7 迁移调用点到新签名：`get_neighbors` → `get_out_hierarchy` / `get_facts`；`delete_edge(src,tgt)` → `delete_edge(edge_id)`；`get_edge(src,tgt)` → `get_edges_between(src,tgt)`（影响 `fanout_reducer` 守门估算 / 重连 / `_migrate_edges` / `_absorb_hub_edges`、`query_engine`、入口插件——全仓搜这三个方法）

## 2. Token 预算（活跃双向视图）

- [x] 2.1 邻域估算计入**事实边渲染 token**，**复用渲染函数**（禁止近似公式）——铁律一（`mcs/core/token_budget.py`）
- [x] 2.2 活跃双向视图组装：{出事实 + 入事实（反查）+ 层级邻居}（**Phase 1 不截断**、返回全部，依赖配置 T 远小于真实窗口；Phase 2 才按 priority 排序截断 ≤ T）

## 3. content 纪律与写入

- [x] 3.1 `extract_concepts` prompt 控长到 **lean 基线（~24 tok；英文约 100 字符；非 200）**；只放定义 + 短叶子属性（`mcs/prompts/extract_concepts.py`）
- [x] 3.2 `judge_relations` + `decisions.py`：`edges_to` 与 `edges_to_names` 均改 `list[dict]`（`target_id` / `target_name` + `label`）；一条关系一个方向一个 label、**不自动镜像**（`mcs/prompts/judge_relations.py`、`mcs/core/decisions.py`）
- [x] 3.3 `_dispatch_create` / `_dispatch_merge` **及第二遍 `edges_to_names` 解析**：均写**一条带 label 事实边、两端索引**（不再双向对存）（`mcs/core/write_pipeline.py` L284-289 / L352-354）
- [x] 3.5 属性升格规则：判定到对外关系的"属性"升格为概念 + 事实边

## 4. Hub / Fanout（只整理活跃集）

- [x] 4.1 fanout 只作用于**出边侧活跃集**：超量出事实 / 子节点经 `decide_hub` 聚 gist hub（`mcs/plugins/maintenance/fanout_reducer.py`）
- [x] 4.2 **入边侧不聚类**，仅靠查询期 priority 截断（Phase 2）
- [x] 4.3 `_exceeds_budget` / `_neighborhood_tokens` = **decide_hub 可行性口径**：中心 content + 层级子节点（`get_out_hierarchy`），**不含事实 token**（decide_hub 看不到事实边、fanout 也聚不了事实）；事实 token 的有界由查询渲染期 Phase 2 截断兜，不进 fanout。`get_out_facts` 留给 Phase 2 查询视图，非 fanout
- [x] 4.4 root 维护适配"可选挂孤儿"：root 仅承载孤儿，不再全量挂接
- [x] 4.5 `_absorb_hub_edges` 成员判定改为 **`kind="hierarchy"` 过滤**（删旧"反向边启发式"`get_edge(t,hub) is None`——存一份模型下失效）；重连 `add_edge` 带正确 `kind`
- [x] 4.6 fanout 内所有 `add_edge` 带 `kind`/`label`/`priority`；**`_rollback_reorg` 恢复边须带全字段**（`add_edge(s,t,kind=e.kind,label=e.label,priority=e.priority)`，否则事实边 label 丢失、kind 退化为 hierarchy）；`_migrate_edges` 去重 `get_edge` → `get_edges_between`

## 5. 查询管线（事实 BFS）

- [x] 5.1 入口：**jieba 切词 + 字面匹配概念名 / 别名**为主力 EntryPlugin（`mcs/plugins/entry/`）
- [x] 5.2 入口兜底：embedding 仅"无字面命中"时启用；root 仅孤儿 / 最后退路
- [x] 5.3 **反查 + 多种子**：命中事实任一端即拉入另一端；多 foothold 扩散激活
- [x] 5.4 `_traverse` 改为**事实 BFS**：每节点渲染活跃双向视图（Phase 1 不截断；Phase 2 priority 截断 ≤ T），LLM **选事实**，端点补入（`mcs/core/query_engine.py`）
- [x] 5.5 **分层分批**：按层级切包（每层 ≤ T），富余合并（沿用贪心打包 T*0.8）
- [x] 5.6 **短边选事实**：优先就近事实；hub 在其层级可见
- [x] 5.7 **entity-anchored**：检索实体作任一端的事实，**不按谓词过滤**；否定 / 极性交 LLM
- [x] 5.8 `query()` 返回 `Subgraph(nodes, edges=选中事实边)`；`focus_id` 设首个种子或置空；后置链兼容 `List[Node]`（取 `.nodes`）
- [x] 5.9 确认 / 声明 `jieba` 依赖：入口分词若用 jieba 且未在 `pyproject.toml` / `requirements` 声明则补上

## 6. LLM 渲染与 Prompt

- [x] 6.1 `ContextRenderer.render_facts(nodes, edges)`：节点 + 事实边统一编号平铺为事实条目（`mcs/core/context_renderer.py`）
- [x] 6.2 新增 `select_facts` purpose + prompt + parser（返回事实编号列表）（`mcs/prompts/select_facts.py`）
- [x] 6.3 事实边渲染 `主 —label→ 宾`；与 2.1 估算共用此渲染（铁律一）

## 7. Phase 2 预留（本期不实现，仅留接口）

- [x] 7.1 `Edge.priority` 字段就位但 Phase 1 **不参与排序 / 截断**；activation 衰减 + 渲染截断为 Phase 2
- [x] 7.2 **不引入溢出索引**（与遗忘架构对立）——评审检查项
- [x] 7.3 孤儿回收钩子占位：遗忘最后一条关联边时改挂 root / 连节点降权（注释 + TODO）

## 8. 测试与评测

- [x] 8.1 单测：Edge(kind/label/priority)、事实边两端索引与反查
- [x] 8.2 单测：活跃双向视图组装与截断；估算含事实 token 且 == 渲染（铁律一）
- [x] 8.3 单测：fanout 只聚出边侧、入边侧不聚类
- [x] 8.4 单测：root 可选挂孤儿（有关联不挂、零关联挂）
- [x] 8.5 单测：事实 BFS 选事实 + 端点补入；短边优先；entity-anchored 反查
- [x] 8.6 单测：极性问题（"是否讨厌"）由 LLM 在正面事实上现推（含 mock LLM）
- [x] 8.7 集成：write→query 全流程，label 正确写入 / 读取 / 反查
- [ ] 8.8 评测：multihop_rag 子集 rebuild + query，对比 hit@10 基线

## 9. 宪法（评审后）

- [x] 9.1 proposal 评审通过后、**实现 invariant 相关代码之前**，按 D7 落 `CLAUDE.md` 核心不变量为"活跃双向视图 ≤ T（有界指活跃视图、非存储）"——使实现期代码与宪法一致；archive 仅最终校对

## 10. 非核心模块迁移（API 波及，须审计 + 迁移）

- [x] 10.1 `plugins/preprocess/cross_doc_linker.py`：`get_edge` → `get_edges_between`；**双向 `add_edge` → 带 label 的单条事实边**；`load_graph_from_db` + `persist_new_edges` 适配新 schema
- [x] 10.2 `plugins/index/community_merger.py`：`get_neighbors` → `get_out_hierarchy`；`add_edge` 带 `kind="hierarchy"`
- [x] 10.3 `diagnostics/graph_quality.py`：`get_neighbors` → `get_out_hierarchy` + `get_facts`（含事实端点）
- [x] 10.4 `stores/in_memory.py` / `sqlite_store.py` 内部 `get_subgraph` 适配新索引结构
- [x] 10.5 全仓终检：`mcs/` 源码中 `get_edge(` / `add_bidirectional(` / 双 `add_edge` 对存 **零残留**（`get_neighbors` 仅 deprecated wrapper 内使用，测试文件通过 wrapper 兼容）

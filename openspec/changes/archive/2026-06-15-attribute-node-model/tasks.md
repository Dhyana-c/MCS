## 1. 模式开关与配置（D1）

- [x] 1.1 `MCSConfig` 增 `relation_model: str = "property_graph"` 字段，取值校验 `{"property_graph", "attribute_node"}`（`mcs/core/config.py`）
- [x] 1.2 `knowledge_graph()` 默认 `property_graph`；暴露 `attribute_node`（新增 `relation_model=` 参数或 `knowledge_graph_attr()` 预设）（`mcs/core/config.py`）
- [x] 1.3 `Phase1Builder` / `presets` 把 `relation_model` 透传给 `WritePipeline` / `QueryEngine` / `ContextRenderer`（`mcs/presets/*`、`mcs/core/builder.py`）
- [x] 1.4 模式单一真相：core 各分支点统一从 config 读 `relation_model`；MUST NOT 散落硬编码默认

## 2. 核心模型与存储——assoc 边（D2 / D8）

- [x] 2.1 `Edge.kind` 增 `"assoc"` 取值；assoc 边 `label` 恒空串、`priority` 恒默认；同步更新 `Edge` docstring（现写"全图两类边"→ 三类）（`mcs/core/graph.py`）
- [x] 2.2 `StoreInterface.add_edge` 放开 `kind="assoc"`（fact label 非空、hierarchy/assoc label 空）；新增抽象 `get_assoc(node_id, limit=None) -> list[Edge]`（该节点作任一端的 assoc 边，反查）（`mcs/core/store.py`）
- [x] 2.3 `InMemoryStore`：`add_edge` kind 改**三分**（hierarchy / fact / assoc；现为 hierarchy/else 二分，assoc 会落入 else 被当 fact，[in_memory.py:135](mcs/stores/in_memory.py:135)）；assoc 走两端索引（独立 `_assoc_by_node`，或共用 `_fact_by_node` 但 `get_facts` / `get_assoc` **MUST 按 kind 过滤隔离**——否则 `get_facts` 返回 assoc）；`get_assoc`；assoc 按 `(source,target)` 去重（label 恒空）；`delete_node` / `_remove_edge_by_id` / `snapshot` / `restore` 覆盖 assoc（独立索引时 `snapshot` MUST 捕获）（`mcs/stores/in_memory.py`）
- [x] 2.4 `SQLiteStore`：边表 `kind` 列**无 CHECK、schema 零改**（迁移零成本）；其内存索引的 `kind=="hierarchy"` 二分逻辑同改**三分**；assoc 两端索引；`get_assoc`（按 kind 过滤）；`save_full` / `load` 逐条保真；快照 / 回滚覆盖 assoc（`mcs/stores/sqlite_store.py`）
- [x] 2.5 `get_assoc` 在 `property_graph` 模式（无 assoc 边）返回空，不报错

## 3. 写入链路——attribute_node 模式（D4）

- [x] 3.1 `decisions.py`：新增关系具体化 action（`create_attribute`，或复活并重定义 `attach_statement`）；`Decision` 增"属性节点 name/content + 端点（id / 同批 name，**去 label**）"字段（`mcs/core/decisions.py`）
- [x] 3.2 `attribute_node` 专属 `judge_relations` prompt + parser：不产 label、产"建/并属性节点 + 连无类型边"意图（`mcs/prompts/judge_relations.py` 或新增模块；经 `prompt_overrides` 按模式注入或按模式选 purpose）
- [x] 3.3 `WritePipeline._apply_decisions` / `_dispatch_*` 按 `relation_model` 分支：`attribute_node` 建属性节点（`role="attribute"`，content 单一说法、**过长则压缩到上限**）+ `add_edge(kind="assoc")`，概念端点连 assoc、字面值内联 content；复用同名去重 / 篇内 name 解析骨架（`mcs/core/write_pipeline.py`）
- [x] 3.4 阶段④调用按模式选 prompt；`property_graph` 分支**保持现状**（基线回归零变化）

## 4. 渲染与估算——口径随模式（D5，铁律一）

- [x] 4.1 `ContextRenderer.render_assoc_edge(edge, node_map=None) -> str`：渲染 `主 — 宾`（**无 label**）（`mcs/core/context_renderer.py`）
- [x] 4.2 `render_facts` **收 `mode` 参数（调用方传，渲染器不持 config）** 按模式平铺关系边：`property_graph` 用 `render_fact_edge`、`attribute_node` 用 `render_assoc_edge`；属性节点按节点渲染（`render_node_full`）；核对全部调用点（`query_engine.py:271` 等）（`mcs/core/context_renderer.py`）
- [x] 4.3 `TokenBudget`：新增 assoc 边估算（复用 `render_assoc_edge`，**禁近似公式**）；活跃视图估算按模式计 assoc / fact token，与渲染逐字一致（`mcs/core/token_budget.py`）

## 5. 查询遍历——事实 BFS（D6）

- [x] 5.1 `QueryEngine._node_view` 按 `relation_model` 取 `get_assoc` / `get_facts` 构建视图；assoc 端点（含属性节点）补入（`mcs/core/query_engine.py`）
- [x] 5.2 `_traverse` 机制不变（分层打包、批量 + 逐节点回退、visited、安全阀），仅关系边来源按模式切换
- [x] 5.3 `query()` 返回 `Subgraph.edges`：`attribute_node` 为 assoc、`property_graph` 为 fact；`_filter_edges_by_nodes` 两模式通用
- [x] 5.4 （可选）`store.get_relations(node_id)` 便捷方法按模式分发（property→fact、attribute→assoc），减少 `query_engine` 分支面

## 6. 守门 / fanout（D7）

- [x] 6.1 fanout 守门口径仍只看**层级出边侧**（中心 content + `get_out_hierarchy`，**不含 assoc/fact token**）；属性节点经 assoc 连接、**不在层级骨架、不参与 fanout 收敛**（其 token 属关系侧，Phase 2 截断兜，见 D7 / 9.5）（`mcs/plugins/maintenance/fanout_reducer.py`）
- [x] 6.2 **（验证，非新增）** 现有 fanout 已正确处理 kind：`_absorb_hub_edges` 只动 hierarchy（:337）、`_migrate_edges` 已 `kind=edge.kind` 保真（:686）、`_rollback_reorg` 走 `store.restore`。仅需验证 assoc 在去重（label 恒空、同对一条）与回滚（独立索引时 snapshot 捕获）下正确（`mcs/plugins/maintenance/fanout_reducer.py`）
- [x] 6.3 **（A1 必修）** `_maintain_seed_root` 孤儿判定按模式：`attribute_node` 模式 MUST 用 `get_assoc`（等价 `get_facts ∪ get_assoc` 皆空才挂 root），否则关系走 assoc 时 `get_facts` 恒空 → 全概念挂 root → **根扁平化破坏不变量**（`mcs/plugins/maintenance/fanout_reducer.py:284`）
- [x] 6.4 可选插件 `community_merger` / `cross_doc_linker` 在 `attribute_node` 模式行为未定义：本期 MUST 不随该模式默认启用（或单独适配其 `get_neighbors` / `add_edge`）（`mcs/plugins/index/community_merger.py`、`mcs/plugins/preprocess/cross_doc_linker.py`）

## 7. 宪法（评审后、实现 mode 分支代码之前）（D9）

- [x] 7.1 proposal 评审通过后，按 D9 改 `CLAUDE.md`「边方向」「核心不变量 / 铁律一」为"关系表示**可插拔**，默认属性图；估算 == 渲染口径随模式"，**再**实现 mode 分支代码；archive 仅最终校对

## 8. 文档

- [x] 8.1 `docs/technical-design.md §2.2` 标注：该"无类型边 + 属性节点"模型即 `attribute_node` 模式，与 `property_graph` 双模式并存（不再是被废弃设计）
- [x] 8.2 `docs/architecture.md`「边的方向」「核心不变量」标注双模式
- [x] 8.3 `docs/core-flows.md` 写入④⑤ / 查询③ 标注 `relation_model` 分支

## 9. 测试与评测

- [x] 9.1 单测：`Edge(kind="assoc")`；assoc 两端索引与反查（`get_assoc` 两端命中）；assoc 去重；**`get_facts` 不返回 assoc、`get_assoc` 不返回 fact（kind 隔离，C4）**（`tests/`）
- [x] 9.2 单测：`attribute_node` 写入——概念-概念关系建属性节点 + 2 条 assoc；概念-字面值建 1 条 assoc + 内联 content；属性节点 `role="attribute"`、无版本列表、**content 过长被压缩到上限（A2）**
- [x] 9.3 单测：`render_assoc_edge` 无 label；属性节点按节点渲染；**估算 == 渲染**（assoc 边、活跃视图，铁律一）
- [x] 9.4 单测：`attribute_node` 查询——`get_assoc` 视图、选关联边补端点、entity-anchored 经属性节点现推（含 mock LLM 极性问题）
- [x] 9.5 单测：**（A1）`attribute_node` 模式有 assoc 关联的概念不挂 root（无根扁平化）、零关联才挂**；守门口径**不含** assoc token；**（B3）属性节点经 assoc 不进 `get_out_hierarchy`、不参与 fanout 收敛**；回滚 / 去重保 `kind="assoc"`
- [x] 9.6 单测：模式开关——`property_graph`（默认）写入 / 查询 / 渲染 / 估算行为**逐字不变**（基线回归）；非法 `relation_model` 取值报错
- [x] 9.7 集成：`attribute_node` write→query 全流程，关系正确建属性节点 / 连 assoc / 反查 / 选中
- [x] 9.8 评测：multihop_rag 子集 `attribute_node` vs `property_graph` hit@10 对比 —— **本期跳过**（attribute_node 为用户可选项、非对比用途；脚本留待按需）
- [x] 9.9 全仓回归：`property_graph` 默认基线测试全绿、行为不变（`.venv\Scripts\python.exe -m pytest -q`）

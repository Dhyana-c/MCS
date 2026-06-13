## 1. 核心模型与存储层

- [ ] 1.1 `Edge` 增 `kind`（`"hierarchy"` | `"fact"`）、`label`、`priority` 字段（`mcs/core/graph.py`）；`Subgraph` 复用既有定义
- [ ] 1.2 `StoreInterface`：事实边**存一份、两端索引**；新增 `get_facts(node_id)`（取该节点作任一端的事实边）、`get_out_hierarchy(node_id)`（层级出边）；`get_neighbors` 拆分为"层级邻居"与"事实邻居"语义（`mcs/core/store.py`）
- [ ] 1.3 反查：`get_facts` MUST 返回该节点为**源或宾**的全部事实边（双向可达）
- [ ] 1.4 `Edge.priority` 持久化；查询取邻域时**按 priority 降序**，截断到预算
- [ ] 1.5 `InMemoryStore` / `SQLiteStore` 适配新 schema（`kind`/`label`/`priority` 列 + 索引）；编写 rebuild 工具
- [ ] 1.6 砍掉初版"降级不删除"相关代码路径

## 2. Token 预算（活跃双向视图）

- [ ] 2.1 邻域估算计入**事实边渲染 token**，**复用渲染函数**（禁止近似公式）——铁律一（`mcs/core/token_budget.py`）
- [ ] 2.2 活跃双向视图组装：{出事实 + 入事实 + 层级邻居} 按 priority 排序、截断到 ≤ T

## 3. content 纪律与写入

- [ ] 3.1 `extract_concepts` prompt 控长到 **lean 基线（~100 字符 / ~24 tok 量级，非 200）**；只放定义 + 短叶子属性（`mcs/prompts/extract_concepts.py`）
- [ ] 3.2 `judge_relations` 输出带 label 的事实边（每方向 label 独立）（`mcs/prompts/judge_relations.py`）
- [ ] 3.3 `_dispatch_create` / `_dispatch_merge` 写**一条事实边、两端索引**（不再双向对存）（`mcs/core/write_pipeline.py`）
- [ ] 3.4 **root 关联可选**：仅当概念与任何既有概念零关联时挂 root（孤儿）；有关联者不挂（`mcs/core/write_pipeline.py` / `fanout_reducer._maintain_seed_root`）
- [ ] 3.5 属性升格规则：判定到对外关系的"属性"升格为概念 + 事实边

## 4. Hub / Fanout（只整理活跃集）

- [ ] 4.1 fanout 只作用于**出边侧活跃集**：超量出事实 / 子节点经 `decide_hub` 聚 gist hub（`mcs/plugins/maintenance/fanout_reducer.py`）
- [ ] 4.2 **入边侧不聚类**，仅靠查询期 priority 截断
- [ ] 4.3 `_exceeds_budget` / `_neighborhood_tokens` 改为按**活跃双向视图**估算（含事实 token，render-consistent）
- [ ] 4.4 root 维护适配"可选挂孤儿"：root 仅承载孤儿，不再全量挂接

## 5. 查询管线（事实 BFS）

- [ ] 5.1 入口：**jieba 切词 + 字面匹配概念名 / 别名**为主力 EntryPlugin（`mcs/plugins/entry/`）
- [ ] 5.2 入口兜底：embedding 仅"无字面命中"时启用；root 仅孤儿 / 最后退路
- [ ] 5.3 **反查 + 多种子**：命中事实任一端即拉入另一端；多 foothold 扩散激活
- [ ] 5.4 `_traverse` 改为**事实 BFS**：每节点渲染活跃双向视图（priority 截断 ≤ T），LLM **选事实**，端点补入（`mcs/core/query_engine.py`）
- [ ] 5.5 **分层分批**：按层级切包（每层 ≤ T），富余合并（沿用贪心打包 T*0.8）
- [ ] 5.6 **短边选事实**：优先就近事实；hub 在其层级可见
- [ ] 5.7 **entity-anchored**：检索实体作任一端的事实，**不按谓词过滤**；否定 / 极性交 LLM
- [ ] 5.8 `query()` 返回 `Subgraph(nodes, edges=选中事实边)`；后置链兼容 `List[Node]`（取 `.nodes`）

## 6. LLM 渲染与 Prompt

- [ ] 6.1 `ContextRenderer.render_facts(nodes, edges)`：节点 + 事实边统一编号平铺为事实条目（`mcs/core/context_renderer.py`）
- [ ] 6.2 新增 `select_facts` purpose + prompt + parser（返回事实编号列表）（`mcs/prompts/select_facts.py`）
- [ ] 6.3 事实边渲染 `主 —label→ 宾`；与 2.1 估算共用此渲染（铁律一）

## 7. Phase 2 预留（本期不实现，仅留接口）

- [ ] 7.1 `Edge.priority` 字段与排序就位，但**不实现衰减策略**
- [ ] 7.2 **不引入溢出索引**（与遗忘架构对立）——评审检查项
- [ ] 7.3 孤儿回收钩子占位：遗忘最后一条关联边时改挂 root / 连节点降权（注释 + TODO）

## 8. 测试与评测

- [ ] 8.1 单测：Edge(kind/label/priority)、事实边两端索引与反查
- [ ] 8.2 单测：活跃双向视图组装与截断；估算含事实 token 且 == 渲染（铁律一）
- [ ] 8.3 单测：fanout 只聚出边侧、入边侧不聚类
- [ ] 8.4 单测：root 可选挂孤儿（有关联不挂、零关联挂）
- [ ] 8.5 单测：事实 BFS 选事实 + 端点补入；短边优先；entity-anchored 反查
- [ ] 8.6 单测：极性问题（"是否讨厌"）由 LLM 在正面事实上现推（含 mock LLM）
- [ ] 8.7 集成：write→query 全流程，label 正确写入 / 读取 / 反查
- [ ] 8.8 评测：multihop_rag 子集 rebuild + query，对比 hit@10 基线

## 9. 宪法（评审后）

- [ ] 9.1 proposal 评审通过后，按 D7 落 `CLAUDE.md` 核心不变量为"活跃双向视图"（archive 时）

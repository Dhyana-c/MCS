# separate-accumulate-frontier

> 状态：proposal（仅设计，未动代码）。本轮 MultiHop-RAG 评测驱动提出。

## Why?

查询阶段③ `_traverse` 当前实装中，`select_facts` 选中的节点**同时**进入 `accumulated`（积累集，进 LLM、吃 T 预算）和 `next_frontier`（待遍历队列）——**两者同源**（见 `query_engine.py:_consume` → `next_frontier`）。

> **注（纠正前一版"根因"措辞）**：此"同源"是 **spec 原设计**，非实装走样——`token-budget-traverse` 的遍历流程 step 5 明确规定"选中邻居 add to `accumulated` and `visited` … enqueue"，选中节点同时进积累集与队列。spec 对二者的区分只在 **token 计量**（队列存引用不吃 T，accumulated 吃 T），**从未要求成员不同**。因此本 change 是**提出新设计**（让二者成员可不同），不是修复偏差。

于是 `accumulated` 的规模完全被 `select_facts` 的召回口径决定。为救 comparison 型 query（旧 prompt 对比较题诱导空返回），`select_facts` 已改为宽召回（宁多勿漏），`accumulated` 随之膨胀到 ~230 节点 / acc_token ≈ T=16K（已撞 T 上限，**不变量本身仍 holding**）。

**框架层问题**：`accumulated` 是"进 LLM、吃 T、最终成为结果"的集合，它的规模 / 确定性是**框架级关注点**——T 预算应花在"确定相关"的内容上，而非宽召回的全部探索候选。但当前"探索召回口径"与"进 LLM 输出口径"被强行绑成一个，宽召回一开，进 LLM 的集合就跟着膨胀。

> **通用性边界（明确不做什么）**：本轮 bench 观察到的两个具体下游症状——① `doc_rerank.aggregate_docs` 跨文档放大、② 中文 content vs 英文 query 的跨语言词法失配——分别是**评测插件层**与**语料层**的杠杆，**不在本 change scope**。本 change 只治**框架层**"探索口径 ≠ 进 LLM 口径"这一通用问题；任何下游、任何语料都受益于"进 LLM 的是精筛集而非宽召回原始集"。doc_rerank / 跨语言留给各自的 change（见 `bench/multihop_rag/REPORT.md` 待办）。

## What Changes?

把"探索召回"与"进 LLM 输出"解耦，由 `select_facts` **同一次 LLM 调用**用双角色标签区分（不引入第二次 LLM、零额外调用成本）：

1. **`select_facts` 输出扩展为双角色**：每个选中条目（节点 / 事实边）标注为 **`结果`**（进 accumulated）/ **`探索`**（进 frontier）/ **两者**。同一次判断里完成"宽探索 + 严结果"。
   - **`探索`（frontier）**：BFS 待扩展，宽口径（涉及查询任一实体 / 主题 / 时间 / 比较对象即可），保证探索不漏。**仅存引用、不进 LLM、不吃 T**。
   - **`结果`（accumulated）**：进 LLM 的输出集，严口径（对回答有贡献）。**吃 T，是 `_traverse` 的返回集**。
2. **frontier 用完即弃**：`_traverse` 仍只返回 `accumulated`。frontier 仅在遍历期驱动下一跳，遍历结束丢弃——这正是解耦的意义：若把 frontier 也返回，`accumulated` 就退化回 frontier 规模，等于没解耦。
3. **路由**：`_consume` 按角色分流——`结果`/两者 → accumulated（吃 T）；`探索`/两者 → frontier（不吃 T）；被选中者（无论角色）均入 visited 防重复展开。选中事实边时，端点归属**随该边角色**。
4. **写侧零变化**：`select_facts_write`（窄召回，写管线阶段②关联定位）prompt 不变、仍返回纯编号；parse 把纯编号归一为"两者"，写路径行为逐字等价。
5. **不变量保持**：`accumulated ≤ T`（token_budget）不变；frontier 不计 T（一直如此）。新增 frontier 规模安全阀防"探索候选无界 → 每轮 LLM 调用爆炸"（见 design D7）。
6. **种子只进 frontier（修正既有 drift）**：种子不再预填 `accumulated`（现状违反 `token-budget-traverse`"accumulated 初始为空"spec），改为只进 `frontier`、首轮经 LLM 双粒度判断归属（标 `结果` 进 accumulated，标 `探索` 继续 frontier）。详见 design D6。

## Impact

- **核心代码**：
  - `mcs/prompts/select_facts.py`：读侧 SYSTEM/USER 改为输出双角色；`parse` 返回结构化结果（含旧 flat-array 兼容）。
  - `mcs/core/query_engine.py` `_traverse`：`_consume` 按角色分流；frontier 安全阀；种子初始化只进 frontier（修正 `query_engine.py:317` 预填 accumulated 的既有 drift，见 design D6）。
- **specs**：
  - `query-pipeline`：MODIFIED「语义理解 Loop 使用 select_facts 筛选候选」「select_facts 采用宽召回口径」；ADDED「frontier 与 accumulated 解耦」。
  - `token-budget-traverse`：MODIFIED 遍历流程 step 5（按角色路由）；ADDED frontier 规模安全阀。
- **下游（间接受益，非本 change 目标）**：accumulated 精简 → 下游候选自然收敛，doc_rerank material 放大压力随之缓解；但 doc_rerank / 跨语言本身**不在本 change 改动**。
- **不变量**：`accumulated ≤ T` 保持；frontier 不计 T。
- **风险 / 验收**：见 `design.md`「验收标准」。底线——全量单测绿、gold 不漏 accumulated、comparison 不复发空返回、写侧逐字等价。bench 复测不在本 change scope（留后续，见 `bench/multihop_rag/REPORT.md` 待办）。

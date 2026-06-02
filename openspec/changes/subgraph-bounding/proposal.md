## Why

节点级 / 文档级 reranker（已归档 `query-rerank-and-persistence` / `bench-doc-rerank`）把当下的检索指标救了起来（文档级 recall@10 0.140→0.503），但量化诊断暴露了更本质的问题：**MCS 名义上是 LLM 语义图游走，实际语义层在空转**——418 query 平均只调 **1.1 次**大模型，召回几乎全靠 `alias_entry` 的词法种子。

根因是图的**纵向抽象层缺失**：设计里「密集邻域 → 提一个中间概念节点」（`decide_hub` / `fanout_reducer`）只实现了一半——只给节点打 `role="hub"` 标记、把合成枢纽记成一句备注，**不真正建节点、不重组边**（注释自承"图手术留待未来"）；触发阈值还硬编码 `12`，在平均度 1.32 的图上几乎不触发。查询时召回的 **~1200 个扁平种子**也只被 `priority_trim` 按 token 预算**暴力截断**，从未归纳成分层的「种子图」。底层还压着一个 token 估计偏差（`len//2` 对英文**高估约 2.3×**），让所有 token-aware 判据失真。结果就是：没有中间概念层 → 种子扁平一大坨 → 语义游走无从展开 → 退化成词法检索。

## What Changes

确立一条**统一原则**：任何节点的子图（邻域渲染）都不能超过上下文窗口能容纳的量；超了就用 **LLM 提一个中间概念节点**把成员归纳、分层。查询召回的种子集视为一个**虚拟根节点**的子图，于是**查询与建图共用同一套 fanout reduction**。

- **修 token 估计**（底座）：`TokenBudget.estimate` 从 `len//2` 改为更准的估法（英文 ~`len/4` / 词数×1.3，或接入分词器）；它是所有 token-aware 判据的地基。
- **token-aware 的 fanout 阈值**：触发改由上下文窗口 / token 预算推导能容纳的邻居数（如 16k → ~32），替掉硬编码 `fanout_threshold=12`。
- **真正实现中间概念提取**：补完 `fanout_reducer`——`decide_hub`（LLM）归纳后**真正创建中间概念节点 + 重组边**形成层次，而非只标记。
- **虚拟根 + 种子图**：查询阶段② 召回的扁平种子集挂一个虚拟根，复用同一套 fanout reduction——种子过多时用 LLM **递归 / 分层归纳**成中间概念、形成分层种子图，替掉 `priority_trim` 的暴力截断。
- **提中间概念是 LLM 调用**（非纯聚类）：建图时每密集区一次、查询时种子图归纳可能多次 → LLM 量会从 1.1 次/query 上升。**这是让语义层真正工作的代价与目的**；测试阶段先接受、聚焦验证机制是否让语义层展开，成本优化留后期。

## Capabilities

### New Capabilities
- `subgraph-bounding`: 子图大小约束 + 中间概念抽象——任何节点（含查询时的虚拟根）的子图超过上下文容量时，用 LLM 归纳出中间概念节点、分层收敛；阈值 token-aware，建图与查询共用同一套机制。

### Modified Capabilities
<!-- 暂不 commit 对 write-pipeline（阶段⑥ compaction）/ query-pipeline（阶段② 种子定位）的 spec 级行为变更：递归归纳机制、阈值参数需先小规模实验定型。先以 New capability + design 的 Open Questions 表达，待定型后再补 Modified delta。 -->

## Impact

- 改：`mcs/core/token_budget.py`（估计）、`mcs/plugins/phase1/fanout_reducer.py`（真正建中间节点 + 重组边）、`mcs/plugins/phase1/priority_trim.py` / `mcs/core/query_engine.py`（阶段② 虚拟根种子图）、`mcs/prompts/decide_hub.py`（归纳提示按需调整）。
- **LLM 调用上升**（提中间概念）——测试阶段先验证机制是否让语义层展开，成本优化后置。
- **测试阶段直接重建图**验证机制（建图时启用中间概念归纳）；offline 增量与不重建优化留后期。
- 与 `graph-construction-quality` 解耦但相关：本 change 是其 §4（hub/社区）的**聚焦+深化**，并扩展到查询时种子图 + token 估计修复；那个研究型大伞留作后续。
- 依赖已归档的序列化 / reload 索引修复（要在现有图上做手术与验证）。
- 验证：图诊断（最大连通分量占比↑ / 孤立率↓）+ 语义遍历是否展开（LLM/query↑、子图分层）+ 候选召回能否突破 86% + recall 增量，并观察 LLM 成本变化。

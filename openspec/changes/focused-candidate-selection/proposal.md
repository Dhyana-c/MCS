# focused-candidate-selection

> 状态：proposal（仅设计，未动代码）。由 agent-vs-框架 MultiHop-RAG 对照实验驱动。

## Why?

本轮把"以 agent 形式（ReAct + deepseek-chat）做检索"与"固定流程框架（BFS + 宽召回 select_facts）"在**同图、同 200 query、同 lexical doc_rerank** 下做了同口径对照（数据见 `bench/multihop_rag/reports/agent_vs_framework.md`，跑批脚本 `bench/multihop_rag/scripts/agent_full_run.py`）。核心发现：

1. **召回（reached / recall@∞）两边接近**：gold 基本都被两边找到（reached ≈ 0.94 持平；完整召回率 agent 0.86 / 框架 0.80，agent 仅微胜）。**瓶颈不在导航/召回。**
2. **差距在排序**：同样找到的 gold，**框架平均排到第 ~18 位（掉出 top-10），agent 排到第 ~7 位**。agent 的 hit@10 / recall@10 因此更高（+0.08 / +0.11）。
3. **机制 = 候选集"聚焦度"**：两边用同一个 doc_rerank。框架的**宽召回 BFS 把大量旁支节点也收进来**，gold 被"词法相似的噪声"淹没、排名压低；agent 带着查询实体定向导航，候选集更聚焦，gold 词法上是主角、浮到前面。
4. **过度探索会埋 gold**：差 case 分析里，agent 的失败一大半是**探爆**（如某题触达 645 节点、gold 被挤到第 210 位）；聚焦反而中。
5. **deepseek 专属约束**：deepseek 在"精细的相关/充分判断"上不稳（见 `docs/select_facts_model_differences.md`：可空就崩、易早停）。框架现有的宽召回 prompt 存在的意义就是**逼它别早停**。任何"让 deepseek 自判够了就停/剪枝"的设计，都要对冲它的过激倾向。

**框架层问题**：固定流程把"探索召回口径"直接当成"进 doc_rerank 的候选集"，候选集被宽召回撑大、稀释排序。需要一个**聚焦候选集**的机制——既不牺牲召回（reached），又把 gold 顶到前面。

> 这复用并延续 `separate-accumulate-frontier` 的"探索口径 ≠ 输出口径"解耦思想：那个 change 让 frontier 与 accumulated 成员可不同；本 change 进一步治理"accumulated → 最终候选集"这一段的聚焦度。

## What Changes?

引入**聚焦候选集选择**。给出两个方案（**deepseek 先走方案 A**；方案 B 为更彻底的备选 / Phase 2）：

### 方案 A（推荐，deepseek 优先）：宽召回不变 + 事后充分性裁剪
- 遍历照常宽探（不早停、不丢召回）。
- 遍历结束后，加一次 LLM **充分性裁剪**：从 accumulated 里选出"足以回答查询的最小聚焦子集"，**只把该子集喂给 doc_rerank**。
- **保留未裁剪集作兜底**：裁剪结果异常（空 / 显著少于阈值）时回退到未裁剪集，杜绝 deepseek 剪过头丢召回。
- 低风险：不碰遍历循环，是 bolt-on；探索期从不早停（不触发 deepseek 的早停弱项）。

### 方案 B（更彻底，备选 / Phase 2）：有界可回访的 LLM 引导遍历
- 把 `_traverse` 从"广度穷尽 BFS"改为"**LLM 当策略、有步数预算（`max_steps`）、可回访**的最佳优先遍历"。
- **去掉 `visited` 永久禁访**，允许节点被再次展开；**回访以"accumulated 自上次该节点裁决后发生变化"为门（进度保证）**，防 deepseek 在热 hub 上空烧预算。
- LLM 每步可**忽略不重要的点**（在源头剪枝、控噪）。
- 本质是"agent 的便宜版"：把 agent 制胜的 LLM 聚焦 + 可回访搬进框架原语，丢掉 ReAct 的上下文膨胀（token 暴涨来源）。**可回访 = 给 deepseek 过激剪枝兜底**（剪错可回收）。
- 高一些的风险：押注 deepseek 的"重要性"判断（有回访兜底）+ 需要把进度保证设计干净。

两方案不互斥，可叠加：**有界引导遍历（B）+ 收尾充分性裁剪（A）**。

## Impact

- **核心代码**（具体取决于选定方案）：
  - 方案 A：`mcs/core/query_engine.py` 遍历收尾处新增充分性裁剪步；新增 `select_sufficient` prompt bundle（`mcs/prompts/`）；可作为 `POSTPROCESS` 或 `TRIM` 插件落点。
  - 方案 B：重写 `_traverse` 的终止与去重逻辑（`max_steps` 取代 `max_rounds`+visited；回访门控）；扩展 `select_facts` 的角色语义（忽略/回访）。
- **specs**：`query-pipeline`（ADDED 聚焦候选集选择 / 充分性裁剪）；方案 B 另涉 `token-budget-traverse`（遍历流程改为步数预算 + 可回访）。
- **评测**：用本轮 `agent_full_run` 同口径对照框架，验证"reached 不降、gold 名次上升、hit@10 提升"。
- **不变量**：`accumulated ≤ T` 保持；裁剪/聚焦只减不增；方案 B 的步数预算与 token 预算正交。
- **deepseek 约束**：A 安全（不早停）；B 靠回访兜底过激——上线前需 deepseek 实测剪枝/回访行为，或先用 GLM 验证可行性。

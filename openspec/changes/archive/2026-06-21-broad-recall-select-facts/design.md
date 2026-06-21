# Design — 读侧 select_facts 宽召回

## 背景与约束

事实筛选（`purpose=select_facts`）位于查询管线阶段 ③ 事实 BFS：每个节点渲染活跃双向视图，LLM 从候选事实条目中选相关编号。原口径为窄召回（"最相关、可直接回答、可空"）。

宪法相关：查询侧 hit / recall 是读路径核心指标；铁律一（估算==渲染）、铁律二（归纳语义）均不涉及筛选召回口径——本变更不触碰守门 / 不变量。

## 决策：读侧宽召回、宁多勿漏

**选定**：读侧筛选改宽召回——只要条目涉及查询中任何实体 / 主题 / 时间 / 比较对象 / 关联事实就纳入；宁可多召回交由后续 `doc_rerank` / 裁剪收敛；候选 ≥5 时至少返回 3 条。

理由：
- MultiHop-RAG 多跳检索，漏一个 gold 文档即损失 hit / recall；窄召回系统性漏召。
- 噪声有下游收敛（`doc_rerank` / 裁剪），多召回的代价可控。
- 评测证实 +0.145 overall hit@10、+0.304 comparison。

**否决**：维持窄召回——与实验数据相悖。

## 已知溢出：写侧共用 _traverse

彼时 `_traverse()` 读写共用、硬编码 `purpose="select_facts"`。本 change 改的是该 purpose 的 prompt，故**宽召回同时作用于写管线阶段 ② 关联定位**（`write_pipeline` → `query_nodes` → `_traverse`）。

- 写侧阶段 ② 目的是精确定位已有相关节点供 `extract_concepts` / `judge_relations` 对齐；宽召回会拉入弱相关节点、抬高对齐误判率。
- 该溢出**未在写侧（建图质量）指标上验证**。
- 对已建图无影响（写路径只在 ingest 触发）；未来 re-ingest 的写侧污染由 `read-write-select-prompt-split` 收口（读写 prompt 解耦、写侧用窄召回 `select_facts_write`）。

本 change 不解决该溢出——只确立"读侧宽召回"这一决定与收益。两个 change 职责正交。

## 影响面

- 读路径：筛选召回口径窄→宽，评测验证 +0.145。
- 守门 / 不变量 / 渲染 / 估算：均不触碰。
- 写路径：受溢出影响（已知，由 read-write change 收口）。

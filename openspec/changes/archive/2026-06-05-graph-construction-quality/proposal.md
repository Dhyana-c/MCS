## Why

MultiHop-RAG 诊断（200 篇共享图）显示 MCS 建出来的图**稀疏且碎片化**：4380 节点 / 2901 边 / 平均度 1.32；**34% 孤立节点**；**1681 个连通分量**（最大仅占 37%）；**跨文档边只有 634 / 2876**。成因是 judge_relations 偏向 "create"（"宁可不合"）、阶段② 锚点召回弱，以及设计文档里的 **CommunityMerger（社区检测/合并）从未实现**。`query-rerank-and-persistence` 已用 reranker 把当下检索指标救起来（recall@10 0.14→0.81），但一张"无向、无类型、还连不起来"的图，限制了真·跨文档多跳推理的上限。本 change 探索如何提升图构建质量——**这是研究型 change，先量化、再实验、后定方案**。

## What Changes

- 新增**图质量诊断**：产出度分布、孤立节点率、连通分量数/最大分量占比、跨文档边比例等结构指标，作为可量化目标与回归基线（concrete，本 change 唯一硬交付）
- **探索**跨文档链接增强：改进阶段② 锚点召回 / 降低 create 偏置 / 或 build 后补一遍跨文档链接 pass（策略待实验）
- **探索**实装 `CommunityMerger`：社区检测（稠密邻域）+ 合并/结构化，接 CompactionPlugin 协议（算法选型待定）
- **（stretch）**探索有向/带类型边是否值得引入（优先级最低，可能拆出）

## Capabilities

### New Capabilities
- `graph-construction-quality`: 图构建质量——可测量的图结构诊断，以及（探索性的）让构建产出更连通图的增强；以诊断为硬约束，构建增强以"可被诊断验证"的较软要求表达

### Modified Capabilities

（本 change 暂不 commit 对 `write-pipeline` / compaction 的 spec 级行为变更——探索阶段先留 Open Questions；待实验定型后再在后续迭代补 Modified delta）

## Impact

- 新增图质量诊断（独立工具或诊断函数），可对任意已落盘图运行
- 探索性改动可能触及 `mcs/core/write_pipeline.py`（阶段② 锚点召回）、新增 community `CompactionPlugin`、judge_relations 提示/策略——但**均待实验确认收益后才落**
- 与 `query-rerank-and-persistence` **解耦**：本 change 不碰 reranker / 持久化
- **高风险、慢收口**（research change 本质）：需先用诊断 + 小规模实验量化"图质量改进在 reranker 已生效后的增量收益"，再决定投入多少
- 依赖 `query-rerank-and-persistence` 的序列化修复：要在已落盘图上跑诊断/实验，需先能正确 reload
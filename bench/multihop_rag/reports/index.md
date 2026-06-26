# MultiHop-RAG 评测报告索引

本目录存放 MultiHop-RAG 评测的实验报告。

## 报告列表

| 文件 | 日期 | 描述 |
|------|------|------|
| [doc_rerank_experiment.md](doc_rerank_experiment.md) | 2026-06-02 | 文档级重排实验报告：recall@10 从 0.140 提升到 0.503 |
| [metrics_1000_full.md](metrics_1000_full.md) | 2026-06-11 | 全量 609 篇 · 1000 query（lexical doc_rerank, T=32k）：hit@10=0.649 |
| [dual_edge_full_608.md](dual_edge_full_608.md) | 2026-06-14 | dual-edge · 全量 608 篇 · 200 query（llm doc_rerank, T=16k, 概念去重后）：**hit@10=0.770**；含 8 项修复 + 去重 before/after + 成本分析 |
| [glm_query_200.md](glm_query_200.md) | 2026-06-15 | GLM-5.1 查询侧（同图换 read 模型）· 全量 200 query（llm doc_rerank, T=16k，分两批续跑）：**hit@10=0.765**（vs deepseek 同图 0.770，基本持平；inference 反超 +5.7pp）；含端点配置文件化 + query 级续跑 + 配额软上限/熔断保护 |
| [agent_vs_framework.md](agent_vs_framework.md) | 2026-06-24 | agent（deepseek ReAct）vs 固定流程框架 · 同图同 200 query 同口径（自动指标表）：**agent hit@10=0.825 vs 框架 0.695** |
| [agent_vs_framework_investigation.md](agent_vs_framework_investigation.md) | 2026-06-24 | 上者的**完整调查报告**：召回/排序拆分、建图非瓶颈审计、闭卷泄漏探针、null 诚实性、差因、成本、两条可移植杠杆 |

## 指标口径

所有报告使用统一的指标口径：

- **文档级检索**：query() 返回的节点经 source_tracking 映射回来源文档
- **指标**：Hit@k / Recall@k / MAP@k / MRR@k
- **null_query 处理**：单独报告 avg_docs_retrieved，不计入主指标

## 对比实验

三类配置的复现命令见 [doc_rerank_experiment.md](doc_rerank_experiment.md#附复现命令)。

- baseline：节点 rank 序映射文档
- 节点级重排：LexicalScorer 对节点打分
- 文档级重排：对候选文档直接打分

# MultiHop-RAG 评测报告索引

本目录存放 MultiHop-RAG 评测的实验报告。

## 报告列表

| 文件 | 日期 | 描述 |
|------|------|------|
| [doc_rerank_experiment.md](doc_rerank_experiment.md) | 2026-06-02 | 文档级重排实验报告：recall@10 从 0.140 提升到 0.503 |

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

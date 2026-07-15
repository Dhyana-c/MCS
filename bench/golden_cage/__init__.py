"""《黄金笼》纯 agent 评测：ReAct agent 建图 + agent 导航查询。

与 ``bench/multihop_rag`` 平级、目录结构相同的中文小说多跳检索评测。
数据集为小说《黄金笼》前 7 章的场景级 corpus（141 篇）+ 150 条 QA
（MultiHop-RAG 格式）。区别于 multihop_rag 的固定流程管线：

- **建图**：``MemoryAgent``（ReAct）逐场景决策写入（learn 底层复用 MCS 写管线 +
  守门；写入文本以场景原文钉死、doc 级 source tracking 由评测侧 Memory 注入）。
- **查询**：``MemoryAgent`` 用 search / associate / reason 等导航工具探索，
  触达节点经 lexical doc_rerank 映射回文档，与 multihop_rag 同口径算
  hit@k / recall@k / mrr@k。
"""

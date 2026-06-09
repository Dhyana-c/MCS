"""MultiHop-RAG 共享语料多跳检索评测。

"一次建图、多 query"：把整个语料摄入**同一个持久化
MCS 实例**（SQLite，非 :memory:），之后对所有 query 做检索评测。主指标是**文档级
检索召回** Hit@k / MAP@k / MRR@k——把 query() 返回的 List[Node] 经 source_tracking
映射回来源文档，与 gold evidence 的来源文档比对。

数据：放在 ``bench/multihop_rag/data/`` 目录下（multihoprag_corpus.json + multihoprag_qa.json）。
"""

from bench.multihop_rag.builder import build_shared_graph, chunk_body
from bench.multihop_rag.data import (
    DEFAULT_CORPUS,
    DEFAULT_QA,
    Evidence,
    MultiHopDataLoader,
    MultiHopDoc,
    MultiHopQuery,
    filter_queries,
)
from bench.multihop_rag.metrics import (
    aggregate_metrics,
    hit_at_k,
    map_at_k,
    mrr_at_k,
    recall_at_k,
    retrieved_docs,
)
from bench.multihop_rag.runner import (
    MultiHopEvalConfig,
    MultiHopEvalRunner,
    main,
)

__all__ = [
    # builder
    "build_shared_graph",
    "chunk_body",
    # data
    "DEFAULT_CORPUS",
    "DEFAULT_QA",
    "Evidence",
    "MultiHopDataLoader",
    "MultiHopDoc",
    "MultiHopQuery",
    "filter_queries",
    # metrics
    "aggregate_metrics",
    "hit_at_k",
    "map_at_k",
    "mrr_at_k",
    "recall_at_k",
    "retrieved_docs",
    # runner
    "MultiHopEvalConfig",
    "MultiHopEvalRunner",
    "main",
]
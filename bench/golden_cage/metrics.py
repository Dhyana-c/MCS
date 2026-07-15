"""《黄金笼》检索指标：与 multihop_rag 完全同口径（re-export）。

文档级 Hit@k / Recall@k / MAP@k / MRR@k；节点 → 文档映射靠
``extensions.source_tracking.sources[].doc_id``（建图时注入场景 title）。
"""

from bench.multihop_rag.metrics import (  # noqa: F401
    aggregate_metrics,
    retrieved_docs,
)

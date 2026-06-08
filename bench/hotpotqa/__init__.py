"""HotpotQA 多跳问答端到端评测框架。

从 HotpotQA 数据加载 → MCS ingest → MCS query → 预测格式转换 → 官方指标计算，
一条命令跑通完整评测流程。
"""

from bench.hotpotqa.runner import (
    HotpotDataLoader,
    HotpotEvalConfig,
    HotpotEvalRunner,
    HotpotItem,
    extract_answer,
    extract_prediction,
    extract_supporting_facts,
    format_context_paragraph,
    ingest_hotpot_item,
    main,
)

__all__ = [
    "HotpotDataLoader",
    "HotpotEvalRunner",
    "HotpotEvalConfig",
    "HotpotItem",
    "extract_answer",
    "extract_prediction",
    "extract_supporting_facts",
    "format_context_paragraph",
    "ingest_hotpot_item",
    "main",
]
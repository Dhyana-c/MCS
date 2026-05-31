"""MCS 评测框架。

提供 HotpotQA 等标准 benchmark 的端到端评测能力。
"""

from __future__ import annotations

from mcs.bench.hotpot import (
    HotpotDataLoader,
    HotpotEvalConfig,
    HotpotEvalRunner,
    HotpotItem,
)

__all__ = [
    "HotpotDataLoader",
    "HotpotEvalRunner",
    "HotpotEvalConfig",
    "HotpotItem",
]

"""MCS 实体包 —— 纯数据模型集中地。

承载全部 dataclass 与模块级常量：图数据结构（``graph``）、写入管线决策数据
（``decisions``）、顶级配置（``config``）。

服务、契约（ABC 接口 / 基类 / 枚举）、异常、含逻辑的值对象（如 ``TokenBudget``，
其估算逻辑依赖 ``ContextRenderer``）留在 ``mcs.core``。实体层**不**反向依赖
``mcs.core`` 的服务 / 契约模块（``graph`` 仅含 dataclass，无 import）。
"""

from __future__ import annotations

from mcs.entities.config import (
    PHASE1_DEFAULT_PLUGINS,
    PHASE1_READ_PLUGINS,
    PHASE1_SHARED_PLUGINS,
    PHASE1_WRITE_PLUGINS,
    MCSConfig,
)
from mcs.entities.decisions import (
    ActionType,
    Community,
    ConceptDraft,
    Decision,
    DecisionList,
    MultiHubDecision,
)
from mcs.entities.graph import Edge, Node, Subgraph

__all__ = [
    # graph
    "Node",
    "Edge",
    "Subgraph",
    # decisions
    "ConceptDraft",
    "Decision",
    "DecisionList",
    "Community",
    "MultiHubDecision",
    "ActionType",
    # config
    "MCSConfig",
    "PHASE1_SHARED_PLUGINS",
    "PHASE1_WRITE_PLUGINS",
    "PHASE1_READ_PLUGINS",
    "PHASE1_DEFAULT_PLUGINS",
]

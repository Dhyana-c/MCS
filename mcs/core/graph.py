"""核心图数据结构。

提供 Node、Edge、Subgraph 数据类。图操作接口定义在 store.py，
具体实现在 mcs.stores 包中。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any


@dataclass
class Node:
    """概念节点（最小核心）。

    所有变量/场景特定字段（别名、摘要、来源、版本、置信度等）通过 ``extensions`` 字典
    由插件挂载。
    """

    id: str
    name: str
    content: str
    role: str = "concept"  # "concept" | "hub" | "attribute"
    extensions: dict[str, Any] = field(default_factory=dict)


@dataclass
class Edge:
    """有向边 ``source → target``。

    全图两类边——层级边 (kind="hierarchy") 与事实边 (kind="fact")。
    层级边：纯下行、无 label，结构骨架。
    事实边：带 label（粗粒度谓词）、带 priority（为遗忘预留），
    一条事实只存一份，但两端邻接都索引到它（支持反查）。
    """

    source_id: str
    target_id: str
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    kind: str = "hierarchy"  # "hierarchy" | "fact"
    label: str = ""  # fact 边 MUST 非空；hierarchy 边 MUST 为空串
    priority: float = 0.0  # Phase 1 仅留字段；Phase 2 用于排序/截断


@dataclass
class Subgraph:
    """以焦点节点为根的子图，受 token 预算限制。"""

    focus_id: str
    nodes: list[Node] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)


# Re-export StoreInterface for convenience (core dependency)
from mcs.core.store import StoreInterface  # noqa: E402

# Backward compatibility aliases
GraphStoreInterface = StoreInterface

__all__ = [
    "Node",
    "Edge",
    "Subgraph",
    "StoreInterface",
    # Backward compatibility
    "GraphStoreInterface",
]
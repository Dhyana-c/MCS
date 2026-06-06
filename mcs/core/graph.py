"""核心图数据结构。

提供 Node、Edge、Subgraph 数据类。图操作接口与实现在 graph_store.py。
"""

from __future__ import annotations

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
    """无类型邻接边。

    方向来源于社区合并；初始值为"bidirectional"。
    """

    source_id: str
    target_id: str
    direction: str = "bidirectional"  # "bidirectional" | "out"


@dataclass
class Subgraph:
    """以焦点节点为根的子图，受 token 预算限制。"""

    focus_id: str
    nodes: list[Node] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)


# Re-export from graph_store.py for backward compatibility
from mcs.core.graph_store import GraphStore, GraphStoreInterface, InMemoryGraphStore  # noqa: E402

__all__ = [
    "Node",
    "Edge",
    "Subgraph",
    "GraphStoreInterface",
    "InMemoryGraphStore",
    "GraphStore",
]

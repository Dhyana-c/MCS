"""Core graph data structures and operations.

See architecture.md §2.1.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Node:
    """Concept node (minimal core).

    All variable / scenario-specific fields (aliases, summary, sources,
    versions, confidence, ...) are mounted via the ``extensions`` dict by
    plugins. See architecture.md §2.1.
    """

    id: str
    name: str
    content: str
    role: str = "concept"  # "concept" | "hub" | "attribute"
    extensions: dict[str, Any] = field(default_factory=dict)


@dataclass
class Edge:
    """Untyped adjacency edge.

    Direction emerges from community merge; initial value is "bidirectional".
    """

    source_id: str
    target_id: str
    direction: str = "bidirectional"  # "bidirectional" | "out"


@dataclass
class Subgraph:
    """A subgraph rooted at a focus node, bounded by token budget."""

    focus_id: str
    nodes: list[Node] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)


class GraphStore:
    """Graph storage operations.

    Phase 1 implementation pending. See architecture.md §2.1.
    """

    def add_node(self, node: Node) -> str:
        raise NotImplementedError("Phase 1 implementation pending")

    def get_node(self, node_id: str) -> Node | None:
        raise NotImplementedError("Phase 1 implementation pending")

    def update_node(self, node_id: str, updates: dict) -> None:
        raise NotImplementedError("Phase 1 implementation pending")

    def delete_node(self, node_id: str) -> None:
        raise NotImplementedError("Phase 1 implementation pending")

    def add_edge(self, source_id: str, target_id: str) -> None:
        raise NotImplementedError("Phase 1 implementation pending")

    def get_neighbors(self, node_id: str) -> list[Node]:
        raise NotImplementedError("Phase 1 implementation pending")

    def get_edge(self, source_id: str, target_id: str) -> Edge | None:
        raise NotImplementedError("Phase 1 implementation pending")

    def delete_edge(self, source_id: str, target_id: str) -> None:
        raise NotImplementedError("Phase 1 implementation pending")

    def get_subgraph(self, node_id: str, max_tokens: int) -> Subgraph:
        raise NotImplementedError("Phase 1 implementation pending")

    def get_all_nodes(self) -> list[Node]:
        raise NotImplementedError("Phase 1 implementation pending")

    def get_all_edges(self) -> list[Edge]:
        raise NotImplementedError("Phase 1 implementation pending")

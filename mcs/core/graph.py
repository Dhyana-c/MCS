"""Core graph data structures and operations.

Phase 1 ships an in-memory ``GraphStore``. Persistence is handled
separately by ``SQLiteStoragePlugin`` (load/save against this in-memory
graph).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Node:
    """Concept node (minimal core).

    All variable / scenario-specific fields (aliases, summary, sources,
    versions, confidence, ...) are mounted via the ``extensions`` dict
    by plugins.
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
    """In-memory graph storage.

    Adjacency is stored as a symmetric dict-of-sets keyed by node id. A
    ``Subgraph`` is built greedily from a focus node by expanding through
    neighbors until the token budget is exhausted.
    """

    def __init__(self) -> None:
        self._nodes: dict[str, Node] = {}
        self._edges: dict[tuple[str, str], Edge] = {}
        self._adjacency: dict[str, set[str]] = {}

    # === Node CRUD ===

    def add_node(self, node: Node) -> str:
        self._nodes[node.id] = node
        self._adjacency.setdefault(node.id, set())
        return node.id

    def get_node(self, node_id: str) -> Node | None:
        return self._nodes.get(node_id)

    def update_node(self, node_id: str, updates: dict) -> None:
        node = self._nodes.get(node_id)
        if node is None:
            return
        for key, value in (updates or {}).items():
            if hasattr(node, key):
                setattr(node, key, value)

    def delete_node(self, node_id: str) -> None:
        if node_id not in self._nodes:
            return
        # Drop all incident edges first.
        for other in list(self._adjacency.get(node_id, set())):
            self.delete_edge(node_id, other)
        self._adjacency.pop(node_id, None)
        self._nodes.pop(node_id, None)

    # === Edge CRUD ===

    def add_edge(
        self,
        source_id: str,
        target_id: str,
        direction: str = "bidirectional",
    ) -> None:
        if source_id == target_id:
            return  # no self-loops
        if source_id not in self._nodes or target_id not in self._nodes:
            return
        # Canonicalize undirected edges so (a,b) and (b,a) collide.
        key = self._edge_key(source_id, target_id, direction)
        if key in self._edges:
            return
        self._edges[key] = Edge(
            source_id=source_id, target_id=target_id, direction=direction
        )
        self._adjacency.setdefault(source_id, set()).add(target_id)
        self._adjacency.setdefault(target_id, set()).add(source_id)

    def get_edge(self, source_id: str, target_id: str) -> Edge | None:
        for direction in ("bidirectional", "out"):
            key = self._edge_key(source_id, target_id, direction)
            edge = self._edges.get(key)
            if edge is not None:
                return edge
        return None

    def delete_edge(self, source_id: str, target_id: str) -> None:
        for direction in ("bidirectional", "out"):
            key = self._edge_key(source_id, target_id, direction)
            self._edges.pop(key, None)
        # If no edge remains between these two, drop adjacency.
        if self.get_edge(source_id, target_id) is None:
            self._adjacency.get(source_id, set()).discard(target_id)
            self._adjacency.get(target_id, set()).discard(source_id)

    # === Queries ===

    def get_neighbors(self, node_id: str) -> list[Node]:
        ids = self._adjacency.get(node_id, set())
        return [self._nodes[i] for i in ids if i in self._nodes]

    def get_subgraph(self, node_id: str, max_tokens: int) -> Subgraph:
        """Greedy BFS expansion from focus, stopping when budget is hit."""
        sub = Subgraph(focus_id=node_id)
        focus = self._nodes.get(node_id)
        if focus is None:
            return sub
        sub.nodes.append(focus)
        used = _rough_estimate(focus.content)
        visited = {node_id}
        frontier = [node_id]
        while frontier:
            next_frontier: list[str] = []
            for current in frontier:
                for neighbor_id in self._adjacency.get(current, set()):
                    if neighbor_id in visited:
                        continue
                    neighbor = self._nodes.get(neighbor_id)
                    if neighbor is None:
                        continue
                    cost = _rough_estimate(neighbor.content)
                    if used + cost > max_tokens:
                        return sub
                    sub.nodes.append(neighbor)
                    used += cost
                    visited.add(neighbor_id)
                    next_frontier.append(neighbor_id)
                    edge = self.get_edge(current, neighbor_id)
                    if edge is not None:
                        sub.edges.append(edge)
            frontier = next_frontier
        return sub

    def get_all_nodes(self) -> list[Node]:
        return list(self._nodes.values())

    def get_all_edges(self) -> list[Edge]:
        return list(self._edges.values())

    # === Internal ===

    @staticmethod
    def _edge_key(
        source_id: str, target_id: str, direction: str
    ) -> tuple[str, str]:
        """Canonical edge key.

        Bidirectional edges are normalized so (a,b) and (b,a) collide;
        directed edges keep their source-target ordering.
        """
        if direction == "bidirectional":
            return (
                (source_id, target_id)
                if source_id < target_id
                else (target_id, source_id)
            )
        return (source_id, target_id)


def _rough_estimate(text: str) -> int:
    """Cheap per-token estimate used inside GraphStore for budget checks."""
    if not text:
        return 0
    # Rough heuristic: 2 chars per token (balances English + CJK).
    return max(1, len(text) // 2)

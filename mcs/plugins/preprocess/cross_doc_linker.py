"""Cross-document linking enhancement for graph quality improvement.

This module provides strategies to increase cross-document connectivity:
1. Name-based linking: Find nodes with similar names across documents
2. Alias-based linking: Match aliases across documents
"""

import json
import shutil
import sqlite3
from collections import defaultdict
from dataclasses import dataclass
from typing import Any

from mcs.entities.graph import CLASS_CONCEPT, EDGE_ASSOC, Edge, Node
from mcs.stores.in_memory import InMemoryStore

GraphStore = InMemoryStore


@dataclass
class CrossDocLinkCandidate:
    """A candidate for cross-document linking."""
    source_id: str
    target_id: str
    source_doc: str
    target_doc: str
    confidence: float
    reason: str  # "name_match", "alias_match", "semantic_similarity"


def find_cross_doc_candidates_by_name(
    graph: GraphStore,
    max_candidates: int = 1000,
) -> list[CrossDocLinkCandidate]:
    """Find cross-document link candidates by matching node names.

    Strategy: Nodes with identical or very similar names across documents
    are likely related concepts that should be connected.

    Args:
        graph: The GraphStore to analyze
        max_candidates: Maximum number of candidates to return

    Returns:
        List of CrossDocLinkCandidate objects
    """
    candidates = []

    # Group nodes by name
    name_to_nodes: dict[str, list[Node]] = defaultdict(list)
    for node in graph.get_all_nodes():
        name_to_nodes[node.name.lower()].append(node)

    # Find names that appear in multiple documents
    for name, nodes in name_to_nodes.items():
        if len(nodes) < 2:
            continue

        # Get unique documents
        docs = set()
        for node in nodes:
            sources = node.extensions.get("source_tracking", {}).get("sources", [])
            if sources:
                docs.add(sources[0].get("doc_id", "unknown"))

        if len(docs) < 2:
            continue  # All nodes from same document, skip

        # Create candidates for nodes from different documents
        for i, node1 in enumerate(nodes):
            sources1 = node1.extensions.get("source_tracking", {}).get("sources", [])
            doc1 = sources1[0].get("doc_id", "unknown") if sources1 else "unknown"

            for node2 in nodes[i+1:]:
                sources2 = node2.extensions.get("source_tracking", {}).get("sources", [])
                doc2 = sources2[0].get("doc_id", "unknown") if sources2 else "unknown"

                if doc1 == doc2:
                    continue  # Same document, skip

                # Check if already connected
                if graph.get_edges_between(node1.id, node2.id):
                    continue

                candidates.append(CrossDocLinkCandidate(
                    source_id=node1.id,
                    target_id=node2.id,
                    source_doc=doc1,
                    target_doc=doc2,
                    confidence=1.0,  # Exact name match
                    reason="name_match",
                ))

    return candidates[:max_candidates]


def find_cross_doc_candidates_by_alias(
    graph: GraphStore,
    max_candidates: int = 1000,
) -> list[CrossDocLinkCandidate]:
    """Find cross-document link candidates by matching aliases.

    Strategy: If a node's name matches another node's alias, they may be
    the same concept expressed differently.

    Args:
        graph: The GraphStore to analyze
        max_candidates: Maximum number of candidates to return

    Returns:
        List of CrossDocLinkCandidate objects
    """
    candidates = []

    # Build name lookup
    name_to_nodes: dict[str, list[Node]] = defaultdict(list)
    for node in graph.get_all_nodes():
        name_to_nodes[node.name.lower()].append(node)

    # Check each node's aliases against other nodes' names
    for node in graph.get_all_nodes():
        aliases = node.extensions.get("alias_index", {}).get("aliases", [])
        sources = node.extensions.get("source_tracking", {}).get("sources", [])
        doc = sources[0].get("doc_id", "unknown") if sources else "unknown"

        for alias in aliases:
            alias_lower = alias.lower()
            if alias_lower not in name_to_nodes:
                continue

            for other_node in name_to_nodes[alias_lower]:
                if other_node.id == node.id:
                    continue  # Same node, skip

                other_sources = other_node.extensions.get("source_tracking", {}).get("sources", [])
                other_doc = other_sources[0].get("doc_id", "unknown") if other_sources else "unknown"

                if doc == other_doc:
                    continue  # Same document, skip

                # Check if already connected
                if graph.get_edges_between(node.id, other_node.id):
                    continue

                candidates.append(CrossDocLinkCandidate(
                    source_id=node.id,
                    target_id=other_node.id,
                    source_doc=doc,
                    target_doc=other_doc,
                    confidence=0.8,  # Alias match is less certain than name match
                    reason="alias_match",
                ))

    return candidates[:max_candidates]


def apply_cross_doc_links(
    graph: GraphStore,
    candidates: list[CrossDocLinkCandidate],
    confidence_threshold: float = 0.8,
) -> tuple[int, list[Edge]]:
    """Apply cross-document links to the graph.

    Args:
        graph: The GraphStore to modify
        candidates: List of candidates to apply
        confidence_threshold: Minimum confidence to apply

    Returns:
        Tuple of (number_applied, list of new edges)
    """
    applied = 0
    new_edges = []

    for candidate in candidates:
        if candidate.confidence < confidence_threshold:
            continue

        # Verify nodes still exist
        if graph.get_node(candidate.source_id) is None:
            continue
        if graph.get_node(candidate.target_id) is None:
            continue

        # Check if edge already exists (either direction)
        if graph.get_edges_between(candidate.source_id, candidate.target_id):
            continue
        if graph.get_edges_between(candidate.target_id, candidate.source_id):
            continue

        # Add cross-document association edge (统一模型：关联边，无 label)
        graph.add_edge(
            candidate.source_id, candidate.target_id,
            type=EDGE_ASSOC,
        )
        edges = graph.get_edges_between(candidate.source_id, candidate.target_id)
        if edges:
            new_edges.append(edges[-1])
            applied += 1

    return applied, new_edges


def cross_doc_link_pass(
    graph: GraphStore,
    strategies: list[str] | None = None,
    confidence_threshold: float = 0.8,
    max_candidates_per_strategy: int = 1000,
) -> tuple[int, list[Edge]]:
    """Run cross-document linking pass on a graph.

    Args:
        graph: The GraphStore to process
        strategies: List of strategies to use
        confidence_threshold: Minimum confidence to apply links
        max_candidates_per_strategy: Max candidates per strategy

    Returns:
        Tuple of (total links applied, list of new edges)
    """
    if strategies is None:
        strategies = ["name_match", "alias_match"]
    all_candidates = []

    if "name_match" in strategies:
        name_candidates = find_cross_doc_candidates_by_name(
            graph, max_candidates=max_candidates_per_strategy
        )
        all_candidates.extend(name_candidates)

    if "alias_match" in strategies:
        alias_candidates = find_cross_doc_candidates_by_alias(
            graph, max_candidates=max_candidates_per_strategy
        )
        all_candidates.extend(alias_candidates)

    # Sort by confidence
    all_candidates.sort(key=lambda c: c.confidence, reverse=True)

    # Apply links
    total_applied, new_edges = apply_cross_doc_links(
        graph, all_candidates, confidence_threshold
    )

    return total_applied, new_edges


def load_graph_from_db(db_path: str) -> GraphStore:
    """Load a GraphStore from a SQLite db (nodes + edges only).

    Lightweight loader that does not require plugin initialization; extension
    blobs are kept as plain dicts (sufficient for name/alias-based linking).

    Args:
        db_path: Path to the SQLite database file.

    Returns:
        A GraphStore populated with the db's nodes and edges.
    """
    graph = GraphStore()
    conn = sqlite3.connect(db_path)
    try:
        for row in conn.execute(
            "SELECT id, name, content, node_class, extensions_json FROM nodes"
        ):
            ext_raw = json.loads(row[4]) if row[4] else {}
            graph.add_node(
                Node(
                    id=row[0],
                    name=row[1],
                    content=row[2] or "",
                    node_class=row[3] or CLASS_CONCEPT,
                    extensions=ext_raw,
                )
            )
        # 用公开 add_edge + edge_id 保留 DB 原始边 id——不再直接操作 store 内部
        # 属性（_nodes / _edges / _assoc_*）。悬空边由 add_edge 的节点存在性守门跳过。
        for row in conn.execute(
            "SELECT id, source_id, target_id, type, priority FROM edges"
        ):
            graph.add_edge(
                row[1],
                row[2],
                type=row[3] or EDGE_ASSOC,
                priority=row[4] if row[4] is not None else 0.0,
                edge_id=row[0],
            )
    finally:
        conn.close()
    return graph


def persist_new_edges(db_path: str, new_edges: list[Edge]) -> int:
    """Write newly-created edges back to the ``edges`` table.

    Uses ``INSERT OR IGNORE`` keyed on the ``id`` primary key (each edge carries
    a unique uuid, so this only guards against re-inserting the exact same edge
    row). Structural dedup is already handled upstream by
    ``apply_cross_doc_links`` (it skips node pairs already connected either way).

    Args:
        db_path: Path to the SQLite database to write to.
        new_edges: Edges produced by the linking pass.

    Returns:
        The number of edge rows actually inserted.
    """
    if not new_edges:
        return 0
    conn = sqlite3.connect(db_path)
    try:
        before = conn.total_changes
        conn.executemany(
            "INSERT OR IGNORE INTO edges (id, source_id, target_id, type, priority) "
            "VALUES (?, ?, ?, ?, ?)",
            [
                (
                    e.id,
                    e.source_id,
                    e.target_id,
                    getattr(e, "type", EDGE_ASSOC),
                    getattr(e, "priority", 0.0),
                )
                for e in new_edges
            ],
        )
        conn.commit()
        inserted = conn.total_changes - before
    finally:
        conn.close()
    return inserted


def cross_doc_link_pass_from_db(
    db_path: str,
    output_db_path: str | None = None,
    strategies: list[str] | None = None,
    confidence_threshold: float = 0.8,
) -> dict[str, Any]:
    """Run cross-document linking on a graph db and persist the new edges.

    Loads the graph from ``db_path``, runs the linking pass in memory, then
    writes the newly-created cross-document edges back to the ``edges`` table.

    Args:
        db_path: Path to input database.
        output_db_path: If given and different from ``db_path``, the input db is
            copied here first and edges are written to the copy (input left
            untouched). If None, edges are written to ``db_path`` in place.
        strategies: List of strategies to use.
        confidence_threshold: Minimum confidence to apply links.

    Returns:
        Dictionary with before/after diagnostics and persistence statistics.
    """
    if strategies is None:
        strategies = ["name_match", "alias_match"]
    from mcs.diagnostics.graph_quality import diagnose_graph

    # Resolve target db: in-place vs copy-to-output.
    target_path = db_path
    if output_db_path and output_db_path != db_path:
        shutil.copy2(db_path, output_db_path)
        target_path = output_db_path

    graph = load_graph_from_db(target_path)
    baseline = diagnose_graph(graph)

    applied, new_edges = cross_doc_link_pass(
        graph, strategies, confidence_threshold
    )

    edges_persisted = persist_new_edges(target_path, new_edges)
    after = diagnose_graph(graph)

    return {
        "db_path": db_path,
        "output_db_path": output_db_path,
        "target_db_path": target_path,
        "baseline": baseline.to_dict(),
        "after": after.to_dict(),
        "links_applied": applied,
        "edges_persisted": edges_persisted,
        "strategies_used": strategies,
        "confidence_threshold": confidence_threshold,
    }
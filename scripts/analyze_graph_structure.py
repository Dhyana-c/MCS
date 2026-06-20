#!/usr/bin/env python
"""Analyze decision patterns in judge_relations output.

This script loads the graph and analyzes:
1. Decision action distribution (merge vs create vs no_op)
2. Cross-document connectivity patterns
3. Edge density per node
"""

import sqlite3
import json
from collections import defaultdict, Counter
from pathlib import Path


def analyze_graph_structure(db_path: str):
    """Analyze the graph structure to understand connectivity patterns."""
    conn = sqlite3.connect(db_path)

    # Get node doc_id mapping
    node_docs = {}
    for row in conn.execute("SELECT id, extensions_json FROM nodes"):
        ext = json.loads(row[1]) if row[1] else {}
        sources = ext.get("source_tracking", {}).get("sources", [])
        if sources:
            node_docs[row[0]] = sources[0].get("doc_id", "unknown")

    # Get edges and analyze cross-doc patterns
    edges = []
    cross_doc_edges = []
    same_doc_edges = []
    edges_by_doc_pair = Counter()

    for row in conn.execute("SELECT source_id, target_id FROM edges"):
        source_doc = node_docs.get(row[0])
        target_doc = node_docs.get(row[1])

        edges.append((row[0], row[1]))

        if source_doc and target_doc:
            if source_doc != target_doc:
                cross_doc_edges.append((row[0], row[1]))
                pair = tuple(sorted([source_doc, target_doc]))
                edges_by_doc_pair[pair] += 1
            else:
                same_doc_edges.append((row[0], row[1]))

    # Analyze node connectivity
    node_degree = defaultdict(int)
    for source, target in edges:
        node_degree[source] += 1
        node_degree[target] += 1

    # Nodes with only same-doc edges
    nodes_only_same_doc = set()
    nodes_with_cross_doc = set()

    for source, target in edges:
        source_doc = node_docs.get(source)
        target_doc = node_docs.get(target)

        if source_doc and target_doc and source_doc != target_doc:
            nodes_with_cross_doc.add(source)
            nodes_with_cross_doc.add(target)
        else:
            nodes_only_same_doc.add(source)
            nodes_only_same_doc.add(target)

    nodes_only_same_doc -= nodes_with_cross_doc

    # Print analysis
    print("=" * 60)
    print("Graph Structure Analysis")
    print("=" * 60)

    print(f"\nTotal nodes: {len(node_docs)}")
    print(f"Total edges: {len(edges)}")

    print(f"\nCross-document edges: {len(cross_doc_edges)} ({len(cross_doc_edges)/len(edges):.1%})")
    print(f"Same-document edges: {len(same_doc_edges)} ({len(same_doc_edges)/len(edges):.1%})")

    print(f"\nNodes with cross-doc connections: {len(nodes_with_cross_doc)} ({len(nodes_with_cross_doc)/len(node_docs):.1%})")
    print(f"Nodes with only same-doc connections: {len(nodes_only_same_doc)} ({len(nodes_only_same_doc)/len(node_docs):.1%})")

    # Degree distribution
    degree_counts = Counter(node_degree.values())
    print("\nDegree distribution:")
    for deg in sorted(degree_counts.keys())[:10]:
        print(f"  Degree {deg}: {degree_counts[deg]} nodes ({degree_counts[deg]/len(node_docs):.1%})")
    if len(degree_counts) > 10:
        high_deg = sum(c for d, c in degree_counts.items() if d >= 10)
        print(f"  Degree >= 10: {high_deg} nodes ({high_deg/len(node_docs):.1%})")

    # Top connected document pairs
    print("\nTop 10 cross-document connections (doc pairs):")
    for pair, count in edges_by_doc_pair.most_common(10):
        print(f"  {pair[0][:30]} <-> {pair[1][:30]}: {count} edges")

    # Hub nodes (high degree)
    print("\nTop 10 hub nodes (highest degree):")
    top_hubs = sorted(node_degree.items(), key=lambda x: x[1], reverse=True)[:10]
    for node_id, deg in top_hubs:
        doc = node_docs.get(node_id, "unknown")
        conn2 = sqlite3.connect(db_path)
        name = conn2.execute("SELECT name FROM nodes WHERE id = ?", (node_id,)).fetchone()
        conn2.close()
        node_name = name[0] if name else "unknown"
        print(f"  [{deg}] {node_name[:40]} (doc: {doc[:30]})")

    conn.close()

    return {
        "total_nodes": len(node_docs),
        "total_edges": len(edges),
        "cross_doc_edges": len(cross_doc_edges),
        "same_doc_edges": len(same_doc_edges),
        "nodes_with_cross_doc": len(nodes_with_cross_doc),
        "nodes_only_same_doc": len(nodes_only_same_doc),
        "edges_by_doc_pair": dict(edges_by_doc_pair),
    }


if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python analyze_graph_structure.py <db_path>")
        sys.exit(1)

    analyze_graph_structure(sys.argv[1])
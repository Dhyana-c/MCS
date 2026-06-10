"""Graph quality diagnostic tools for measuring structural connectivity metrics."""

import json
from collections import defaultdict
from dataclasses import dataclass, asdict
from typing import TextIO

from mcs.core.graph import Node, Edge
from mcs.core.store import StoreInterface


@dataclass
class GraphQualityReport:
    """Structural connectivity metrics for a knowledge graph.

    Attributes:
        node_count: Total number of nodes in the graph
        edge_count: Total number of edges in the graph
        avg_degree: Average node degree (2 * edges / nodes)
        isolated_node_count: Number of nodes with degree 0
        isolated_node_rate: Fraction of nodes that are isolated
        connected_component_count: Number of connected components
        largest_component_size: Size of the largest connected component
        largest_component_ratio: Fraction of nodes in the largest component
        cross_doc_edge_count: Number of edges connecting nodes from different documents
        cross_doc_edge_rate: Fraction of edges that are cross-document
        node_role_distribution: Count of nodes by role (concept, hub, attribute)
    """
    node_count: int
    edge_count: int
    avg_degree: float
    isolated_node_count: int
    isolated_node_rate: float
    connected_component_count: int
    largest_component_size: int
    largest_component_ratio: float
    cross_doc_edge_count: int
    cross_doc_edge_rate: float
    node_role_distribution: dict[str, int]

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return asdict(self)

    def to_json(self, indent: int = 2) -> str:
        """Serialize to JSON string."""
        return json.dumps(self.to_dict(), indent=indent, ensure_ascii=False)

    def print_summary(self, file: TextIO | None = None) -> None:
        """Print a human-readable summary to terminal or file."""
        print("=" * 60, file=file)
        print("Graph Quality Diagnostic Report", file=file)
        print("=" * 60, file=file)
        print(f"Nodes: {self.node_count:,}", file=file)
        print(f"Edges: {self.edge_count:,}", file=file)
        print(f"Average Degree: {self.avg_degree:.2f}", file=file)
        print(file=file)
        print("Connectivity:", file=file)
        print(f"  Isolated Nodes: {self.isolated_node_count:,} ({self.isolated_node_rate:.1%})", file=file)
        print(f"  Connected Components: {self.connected_component_count:,}", file=file)
        print(f"  Largest Component: {self.largest_component_size:,} nodes ({self.largest_component_ratio:.1%})", file=file)
        print(file=file)
        print("Cross-Document Connectivity:", file=file)
        print(f"  Cross-Doc Edges: {self.cross_doc_edge_count:,} ({self.cross_doc_edge_rate:.1%})", file=file)
        print(file=file)
        print("Node Roles:", file=file)
        for role, count in sorted(self.node_role_distribution.items()):
            pct = count / self.node_count if self.node_count > 0 else 0
            print(f"  {role}: {count:,} ({pct:.1%})", file=file)
        print("=" * 60, file=file)


def _get_node_doc_id(node: Node) -> str | None:
    """Extract the primary document ID from a node's source tracking.

    Returns the first source's doc_id if available, else None.
    """
    sources = node.extensions.get("source_tracking", {}).get("sources", [])
    if sources and len(sources) > 0:
        return sources[0].get("doc_id")
    return None


def _compute_connected_components(store: StoreInterface) -> list[set[str]]:
    """Find all connected components using BFS.

    Returns a list of sets, each set containing node IDs in one component.
    """
    visited = set()
    components = []

    for node in store.get_all_nodes():
        if node.id in visited:
            continue

        # BFS from this node
        component = set()
        queue = [node.id]

        while queue:
            current_id = queue.pop(0)
            if current_id in visited:
                continue

            visited.add(current_id)
            component.add(current_id)

            # Add all neighbors to queue
            neighbors = store.get_neighbors(current_id)
            for neighbor in neighbors:
                if neighbor.id not in visited:
                    queue.append(neighbor.id)

        if component:
            components.append(component)

    return components


def diagnose_graph(store: StoreInterface) -> GraphQualityReport:
    """Compute structural connectivity metrics for a graph.

    Args:
        store: The StoreInterface to analyze

    Returns:
        GraphQualityReport with all computed metrics
    """
    nodes = store.get_all_nodes()
    edges = store.get_all_edges()

    node_count = len(nodes)
    edge_count = len(edges)

    # Average degree: each edge contributes 2 to total degree
    avg_degree = (2 * edge_count / node_count) if node_count > 0 else 0.0

    # Compute degree for each node
    node_degrees = defaultdict(int)
    for edge in edges:
        node_degrees[edge.source_id] += 1
        node_degrees[edge.target_id] += 1

    # Isolated nodes (degree 0)
    isolated_node_count = sum(1 for node in nodes if node_degrees.get(node.id, 0) == 0)
    isolated_node_rate = isolated_node_count / node_count if node_count > 0 else 0.0

    # Connected components
    components = _compute_connected_components(store)
    connected_component_count = len(components)

    # Largest component
    largest_component_size = max((len(c) for c in components), default=0)
    largest_component_ratio = largest_component_size / node_count if node_count > 0 else 0.0

    # Cross-document edges
    node_doc_ids = {node.id: _get_node_doc_id(node) for node in nodes}
    cross_doc_edge_count = 0
    for edge in edges:
        source_doc = node_doc_ids.get(edge.source_id)
        target_doc = node_doc_ids.get(edge.target_id)
        # Edge is cross-document if both nodes have doc_ids and they differ
        if source_doc is not None and target_doc is not None and source_doc != target_doc:
            cross_doc_edge_count += 1

    cross_doc_edge_rate = cross_doc_edge_count / edge_count if edge_count > 0 else 0.0

    # Node role distribution
    node_role_distribution = defaultdict(int)
    for node in nodes:
        node_role_distribution[node.role] += 1

    return GraphQualityReport(
        node_count=node_count,
        edge_count=edge_count,
        avg_degree=avg_degree,
        isolated_node_count=isolated_node_count,
        isolated_node_rate=isolated_node_rate,
        connected_component_count=connected_component_count,
        largest_component_size=largest_component_size,
        largest_component_ratio=largest_component_ratio,
        cross_doc_edge_count=cross_doc_edge_count,
        cross_doc_edge_rate=cross_doc_edge_rate,
        node_role_distribution=dict(node_role_distribution),
    )


def diagnose_from_db(db_path: str) -> GraphQualityReport:
    """Load a graph from SQLite database and compute diagnostics.

    This is a minimal loader that doesn't require full plugin initialization.
    It loads nodes and edges directly from the database.

    Args:
        db_path: Path to the SQLite database file

    Returns:
        GraphQualityReport with all computed metrics
    """
    import sqlite3

    from mcs.stores.in_memory import InMemoryStore
    from mcs.core.graph import Node, Edge

    graph = InMemoryStore()
    conn = sqlite3.connect(db_path)

    # Load nodes
    for row in conn.execute(
        "SELECT id, name, content, role, extensions_json FROM nodes"
    ):
        ext_raw = json.loads(row[4]) if row[4] else {}
        # Keep extensions as-is (they're already deserialized from JSON)
        graph.add_node(
            Node(
                id=row[0],
                name=row[1],
                content=row[2] or "",
                role=row[3] or "concept",
                extensions=ext_raw,
            )
        )

    # Load edges
    for row in conn.execute(
        "SELECT source_id, target_id FROM edges"
    ):
        graph.add_edge(row[0], row[1])

    conn.close()
    return diagnose_graph(graph)


def compare_reports(before: GraphQualityReport, after: GraphQualityReport) -> dict:
    """Compare two diagnostic reports and compute deltas.

    Args:
        before: Baseline report
        after: New report after changes

    Returns:
        Dictionary with absolute values and deltas for each metric
    """
    def delta(key: str) -> dict:
        before_val = getattr(before, key)
        after_val = getattr(after, key)
        return {
            "before": before_val,
            "after": after_val,
            "delta": after_val - before_val,
            "delta_pct": (after_val - before_val) / before_val if before_val != 0 else 0.0,
        }

    return {
        "node_count": delta("node_count"),
        "edge_count": delta("edge_count"),
        "avg_degree": delta("avg_degree"),
        "isolated_node_count": delta("isolated_node_count"),
        "isolated_node_rate": delta("isolated_node_rate"),
        "connected_component_count": delta("connected_component_count"),
        "largest_component_size": delta("largest_component_size"),
        "largest_component_ratio": delta("largest_component_ratio"),
        "cross_doc_edge_count": delta("cross_doc_edge_count"),
        "cross_doc_edge_rate": delta("cross_doc_edge_rate"),
    }

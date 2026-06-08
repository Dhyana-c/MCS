"""Unit tests for CommunityMerger plugin."""

import pytest
from mcs.core.graph import Node
from mcs.plugins.index.community_merger import CommunityMergerPlugin
from mcs.stores.in_memory import InMemoryStore

GraphStore = InMemoryStore


def create_dense_community_graph() -> GraphStore:
    """Create a graph with a dense community structure.

    Structure:
        Center A has 12 neighbors (B1-B12)
        Neighbors are interconnected: each Bi connects to Bi+1, Bi+2
        High clustering coefficient around A

    This should trigger community merge.
    """
    graph = GraphStore()

    # Create center node
    center = Node(id="center", name="Center A", content="Central node", role="concept",
                  extensions={"source_tracking": {"sources": [{"doc_id": "doc1"}]}})
    graph.add_node(center)

    # Create neighbors
    neighbors = []
    for i in range(1, 13):
        n = Node(
            id=f"neighbor_{i}",
            name=f"B{i}",
            content=f"Neighbor {i}",
            role="concept",
            extensions={"source_tracking": {"sources": [{"doc_id": f"doc{i % 3 + 1}"}]}},
        )
        graph.add_node(n)
        neighbors.append(n)
        graph.add_edge(center.id, n.id)

    # Add inter-neighbor edges (creates high clustering)
    for i, n1 in enumerate(neighbors):
        # Connect to next 2 neighbors
        for j in range(1, 3):
            n2 = neighbors[(i + j) % len(neighbors)]
            graph.add_edge(n1.id, n2.id)

    return graph


def test_clustering_coefficient_calculation():
    """Test that clustering coefficient is calculated correctly."""
    graph = create_dense_community_graph()
    plugin = CommunityMergerPlugin()

    center = graph.get_node("center")
    neighbors = graph.get_neighbors("center")

    # Calculate clustering coefficient
    clustering = plugin._calc_clustering_coefficient("center", neighbors, graph)

    # Should be high (neighbors are interconnected)
    assert clustering > 0.3, f"Expected high clustering, got {clustering}"


def test_find_community_centers():
    """Test that high-degree nodes are identified as community centers."""
    graph = create_dense_community_graph()
    plugin = CommunityMergerPlugin()

    centers = plugin._find_community_centers(graph)

    # Center node should be identified
    center_ids = [c[0].id for c in centers]
    assert "center" in center_ids


def test_should_run_returns_true_for_changed_nodes():
    """Test that should_run returns True when there are changed nodes."""
    graph = create_dense_community_graph()
    plugin = CommunityMergerPlugin()

    center = graph.get_node("center")
    result = plugin.should_run([center], graph)

    assert result is True


def test_get_neighbor_docs():
    """Test that document IDs are extracted correctly."""
    graph = create_dense_community_graph()
    plugin = CommunityMergerPlugin()

    neighbors = graph.get_neighbors("center")
    docs = plugin._get_neighbor_docs(neighbors)

    # Should have docs from doc1, doc2, doc3
    assert len(docs) >= 1


def test_community_merge_with_mock_llm():
    """Test that community merge creates a hub node."""
    graph = create_dense_community_graph()
    plugin = CommunityMergerPlugin(config={"min_degree": 10, "min_clustering": 0.2})

    center = graph.get_node("center")

    # Mock LLM caller
    class MockDecision:
        synthetic_hub_summary = "Test community hub"

    def mock_llm_caller(purpose, nodes_in, free_args):
        return MockDecision()

    # Run merge
    initial_edge_count = len(graph.get_all_edges())
    plugin.run([center], graph, mock_llm_caller)

    # Check that hub was created
    hubs = [n for n in graph.get_all_nodes() if n.role == "hub"]
    assert len(hubs) >= 1, "Expected hub node to be created"

    # Check that edges increased
    new_edge_count = len(graph.get_all_edges())
    assert new_edge_count > initial_edge_count, "Expected more edges after merge"


def test_no_merge_for_low_clustering():
    """Test that low-clustering communities are not merged."""
    # Create a star graph (low clustering)
    graph = GraphStore()

    center = Node(id="center", name="Center", content="Central", role="concept")
    graph.add_node(center)

    for i in range(15):
        n = Node(id=f"n{i}", name=f"N{i}", content=f"Node {i}", role="concept")
        graph.add_node(n)
        graph.add_edge(center.id, n.id)
        # No inter-neighbor edges = low clustering

    plugin = CommunityMergerPlugin(config={"min_clustering": 0.3})

    clustering = plugin._calc_clustering_coefficient(
        "center", graph.get_neighbors("center"), graph
    )

    # Star graph has clustering = 0
    assert clustering == 0.0, f"Expected 0 clustering for star graph, got {clustering}"

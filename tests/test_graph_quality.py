"""Unit tests for graph quality diagnostic."""

import pytest
from mcs.core.graph import Node, Edge
from mcs.diagnostics.graph_quality import diagnose_graph, GraphQualityReport
from mcs.stores.in_memory import InMemoryStore

GraphStore = InMemoryStore


def create_test_graph() -> GraphStore:
    """Create a test graph with known structure.

    Structure:
        A -- B -- C    D (isolated)    E -- F
             |                         |
             G                        H

    Components:
        - {A, B, C, G}: 4 nodes, 3 edges
        - {D}: isolated
        - {E, F, H}: 3 nodes, 2 edges

    Cross-doc edges:
        - A(doc1) -- B(doc2): cross-doc
        - B(doc2) -- C(doc2): same-doc
        - B(doc2) -- G(doc2): same-doc
        - E(doc3) -- F(doc3): same-doc
        - F(doc3) -- H(doc3): same-doc

    Node roles:
        - A, B, E, F: concept
        - C, G, H: hub
        - D: attribute
    """
    graph = GraphStore()

    # Create nodes with source tracking
    nodes = [
        Node(id="a", name="A", content="Node A", role="concept",
             extensions={"source_tracking": {"sources": [{"doc_id": "doc1"}]}}),
        Node(id="b", name="B", content="Node B", role="concept",
             extensions={"source_tracking": {"sources": [{"doc_id": "doc2"}]}}),
        Node(id="c", name="C", content="Node C", role="hub",
             extensions={"source_tracking": {"sources": [{"doc_id": "doc2"}]}}),
        Node(id="d", name="D", content="Node D", role="attribute",
             extensions={"source_tracking": {"sources": [{"doc_id": "doc1"}]}}),
        Node(id="e", name="E", content="Node E", role="concept",
             extensions={"source_tracking": {"sources": [{"doc_id": "doc3"}]}}),
        Node(id="f", name="F", content="Node F", role="concept",
             extensions={"source_tracking": {"sources": [{"doc_id": "doc3"}]}}),
        Node(id="g", name="G", content="Node G", role="hub",
             extensions={"source_tracking": {"sources": [{"doc_id": "doc2"}]}}),
        Node(id="h", name="H", content="Node H", role="hub",
             extensions={"source_tracking": {"sources": [{"doc_id": "doc3"}]}}),
    ]

    for node in nodes:
        graph.add_node(node)

    # Create edges
    edges = [
        Edge(source_id="a", target_id="b"),  # cross-doc (doc1-doc2)
        Edge(source_id="b", target_id="c"),  # same-doc (doc2)
        Edge(source_id="b", target_id="g"),  # same-doc (doc2)
        Edge(source_id="e", target_id="f"),  # same-doc (doc3)
        Edge(source_id="f", target_id="h"),  # same-doc (doc3)
    ]

    for edge in edges:
        graph.add_edge(edge.source_id, edge.target_id)

    return graph


def test_diagnose_basic_metrics():
    """Test basic node and edge counts."""
    graph = create_test_graph()
    report = diagnose_graph(graph)

    assert report.node_count == 8
    assert report.edge_count == 5
    # Average degree = 2 * edges / nodes = 10 / 8 = 1.25
    assert report.avg_degree == pytest.approx(1.25)


def test_diagnose_isolated_nodes():
    """Test isolated node detection."""
    graph = create_test_graph()
    report = diagnose_graph(graph)

    # Only D is isolated
    assert report.isolated_node_count == 1
    assert report.isolated_node_rate == pytest.approx(1 / 8)


def test_diagnose_connected_components():
    """Test connected component analysis."""
    graph = create_test_graph()
    report = diagnose_graph(graph)

    # Three components: {A,B,C,G}, {D}, {E,F,H}
    assert report.connected_component_count == 3
    # Largest component has 4 nodes
    assert report.largest_component_size == 4
    assert report.largest_component_ratio == pytest.approx(4 / 8)


def test_diagnose_cross_doc_edges():
    """Test cross-document edge detection."""
    graph = create_test_graph()
    report = diagnose_graph(graph)

    # Only A(doc1) -- B(doc2) is cross-document
    assert report.cross_doc_edge_count == 1
    assert report.cross_doc_edge_rate == pytest.approx(1 / 5)


def test_diagnose_node_roles():
    """Test node role distribution."""
    graph = create_test_graph()
    report = diagnose_graph(graph)

    assert report.node_role_distribution["concept"] == 4
    assert report.node_role_distribution["hub"] == 3
    assert report.node_role_distribution["attribute"] == 1


def test_diagnose_empty_graph():
    """Test diagnostics on empty graph."""
    graph = GraphStore()
    report = diagnose_graph(graph)

    assert report.node_count == 0
    assert report.edge_count == 0
    assert report.avg_degree == 0.0
    assert report.isolated_node_count == 0
    assert report.isolated_node_rate == 0.0
    assert report.connected_component_count == 0
    assert report.largest_component_size == 0
    assert report.largest_component_ratio == 0.0
    assert report.cross_doc_edge_count == 0
    assert report.cross_doc_edge_rate == 0.0


def test_report_serialization():
    """Test JSON serialization and summary output."""
    graph = create_test_graph()
    report = diagnose_graph(graph)

    # Test to_dict
    d = report.to_dict()
    assert d["node_count"] == 8
    assert d["edge_count"] == 5

    # Test to_json
    json_str = report.to_json()
    assert '"node_count": 8' in json_str

    # Test print_summary (should not raise)
    import io
    output = io.StringIO()
    report.print_summary(file=output)
    summary = output.getvalue()
    assert "Nodes: 8" in summary
    assert "Edges: 5" in summary


def test_node_without_source_tracking():
    """Test that nodes without source_tracking are handled."""
    graph = GraphStore()

    # Node without source_tracking extension
    graph.add_node(Node(id="a", name="A", content="Node A", role="concept", extensions={}))
    graph.add_node(Node(id="b", name="B", content="Node B", role="concept",
                        extensions={"source_tracking": {"sources": [{"doc_id": "doc1"}]}}))
    graph.add_edge("a", "b")

    report = diagnose_graph(graph)

    # a has no doc_id, b has doc_id -> not cross-doc
    assert report.cross_doc_edge_count == 0

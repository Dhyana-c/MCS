"""Unit tests for the cross-document linking enhancement."""

import json
import sqlite3

import pytest

from mcs.core.graph import Node
from mcs.diagnostics.graph_quality import diagnose_graph
from mcs.plugins.phase1.cross_doc_linker import (
    cross_doc_link_pass,
    cross_doc_link_pass_from_db,
    find_cross_doc_candidates_by_name,
    find_cross_doc_candidates_by_alias,
    load_graph_from_db,
    persist_new_edges,
)
from mcs.stores.in_memory import InMemoryStore

GraphStore = InMemoryStore


def _node(node_id: str, name: str, doc_id: str, aliases=None) -> Node:
    ext = {"source_tracking": {"sources": [{"doc_id": doc_id}]}}
    if aliases:
        ext["alias_index"] = {"aliases": aliases}
    return Node(id=node_id, name=name, content="", role="concept", extensions=ext)


def _graph(*nodes: Node) -> GraphStore:
    g = GraphStore()
    for n in nodes:
        g.add_node(n)
    return g


# === candidate discovery ===


def test_name_match_across_docs():
    """Same name in different docs yields exactly one candidate."""
    g = _graph(_node("a", "Apple", "doc1"), _node("b", "Apple", "doc2"))
    candidates = find_cross_doc_candidates_by_name(g)
    assert len(candidates) == 1
    c = candidates[0]
    assert {c.source_id, c.target_id} == {"a", "b"}
    assert c.reason == "name_match"
    assert c.confidence == 1.0


def test_name_match_same_doc_skipped():
    """Same name within one doc is not a cross-doc candidate."""
    g = _graph(_node("a", "Apple", "doc1"), _node("b", "Apple", "doc1"))
    assert find_cross_doc_candidates_by_name(g) == []


def test_name_match_already_connected_skipped():
    """Already-connected nodes are not re-proposed."""
    g = _graph(_node("a", "Apple", "doc1"), _node("b", "Apple", "doc2"))
    g.add_edge("a", "b")
    assert find_cross_doc_candidates_by_name(g) == []


def test_alias_match_across_docs():
    """A node whose alias matches another node's name across docs is a candidate."""
    g = _graph(
        _node("a", "Big Apple", "doc1", aliases=["NYC"]),
        _node("b", "NYC", "doc2"),
    )
    candidates = find_cross_doc_candidates_by_alias(g)
    assert len(candidates) == 1
    assert candidates[0].reason == "alias_match"
    assert candidates[0].confidence == pytest.approx(0.8)


# === in-memory pass ===


def test_pass_applies_and_is_idempotent():
    """The in-memory pass adds an edge once; a second run adds none."""
    g = _graph(_node("a", "Apple", "doc1"), _node("b", "Apple", "doc2"))

    applied, new_edges = cross_doc_link_pass(g)
    assert applied == 1
    assert len(new_edges) == 1
    assert g.get_edge("a", "b") is not None

    applied2, new_edges2 = cross_doc_link_pass(g)
    assert applied2 == 0
    assert new_edges2 == []


# === db persistence ===


def _make_db(path, nodes, edges=()):
    conn = sqlite3.connect(path)
    conn.execute(
        "CREATE TABLE nodes (id TEXT PRIMARY KEY, name TEXT NOT NULL, "
        "content TEXT, role TEXT DEFAULT 'concept', extensions_json TEXT)"
    )
    conn.execute(
        "CREATE TABLE edges (source_id TEXT, target_id TEXT, "
        "direction TEXT DEFAULT 'bidirectional', "
        "PRIMARY KEY (source_id, target_id, direction))"
    )
    for n in nodes:
        conn.execute(
            "INSERT INTO nodes (id, name, content, role, extensions_json) "
            "VALUES (?, ?, ?, ?, ?)",
            (n.id, n.name, n.content, n.role, json.dumps(n.extensions)),
        )
    for s, t in edges:
        conn.execute(
            "INSERT INTO edges (source_id, target_id, direction) VALUES (?, ?, ?)",
            (s, t, "bidirectional"),
        )
    conn.commit()
    conn.close()


def test_persist_round_trip_in_place(tmp_path):
    """Running the db pass in place persists new cross-doc edges to disk."""
    db = tmp_path / "graph.db"
    _make_db(db, [_node("a", "Apple", "doc1"), _node("b", "Apple", "doc2")])

    result = cross_doc_link_pass_from_db(str(db))
    assert result["links_applied"] == 1
    assert result["edges_persisted"] == 1
    assert result["baseline"]["cross_doc_edge_count"] == 0
    assert result["after"]["cross_doc_edge_count"] == 1

    # Reload from disk and confirm the edge survived the round-trip.
    reloaded = load_graph_from_db(str(db))
    assert reloaded.get_edge("a", "b") is not None
    assert diagnose_graph(reloaded).cross_doc_edge_count == 1


def test_output_copy_leaves_input_untouched(tmp_path):
    """With output_db_path, the input db is unchanged and the copy holds new edges."""
    src = tmp_path / "in.db"
    out = tmp_path / "out.db"
    _make_db(src, [_node("a", "Apple", "doc1"), _node("b", "Apple", "doc2")])

    result = cross_doc_link_pass_from_db(str(src), output_db_path=str(out))
    assert result["target_db_path"] == str(out)
    assert result["edges_persisted"] == 1

    # Input untouched; output has the new edge.
    assert diagnose_graph(load_graph_from_db(str(src))).cross_doc_edge_count == 0
    assert load_graph_from_db(str(out)).get_edge("a", "b") is not None


def test_persist_new_edges_empty_is_noop(tmp_path):
    """persist_new_edges with no edges is a no-op returning 0."""
    db = tmp_path / "graph.db"
    _make_db(db, [_node("a", "Apple", "doc1")])
    assert persist_new_edges(str(db), []) == 0

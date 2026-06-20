"""Source 规则入库测试（ingest_source）。

覆盖 #28：source 按类型切分分类、保真存入、不经 LLM。
"""

from __future__ import annotations

import pytest

from mcs.core.plugin_manager import PluginManager
from mcs.core.query_engine import QueryEngine
from mcs.core.store import StoreInterface
from mcs.core.token_budget import TokenBudget
from mcs.core.write_pipeline import WritePipeline
from mcs.entities.decisions import SourceData
from mcs.entities.graph import CLASS_CONCEPT, CLASS_SOURCE, EDGE_ASSOC, Node


def _make_pipeline(store: StoreInterface, mock_llm) -> WritePipeline:
    pm = PluginManager()
    pm.register(mock_llm)
    tb = TokenBudget(8000)
    qe = QueryEngine(store=store, llm=mock_llm, plugin_manager=pm, token_budget=tb)
    return WritePipeline(
        store=store,
        llm=mock_llm,
        query_engine=qe,
        plugin_manager=pm,
        token_budget=tb,
    )


def test_ingest_source_creates_source_node(empty_graph, mock_llm):
    """ingest_source 创建 node_class=="source" 的节点。"""
    wp = _make_pipeline(empty_graph, mock_llm)
    result = wp.ingest_source(SourceData(name="test.pdf", source_type="file"))
    assert len(result) == 1
    assert result[0].node_class == CLASS_SOURCE
    assert result[0].name == "test.pdf"


def test_ingest_source_with_chunks(empty_graph, mock_llm):
    """有 chunks 时每个 chunk 对应一个 source 节点。"""
    wp = _make_pipeline(empty_graph, mock_llm)
    result = wp.ingest_source(
        SourceData(
            name="report.pdf",
            source_type="file",
            chunks=[
                {"content": "第一段内容", "chunk_index": 0},
                {"content": "第二段内容", "chunk_index": 1},
            ],
        )
    )
    assert len(result) == 2
    assert all(n.node_class == CLASS_SOURCE for n in result)
    # 每个 chunk 节点的 content 不同
    contents = {n.content for n in result}
    assert "第一段内容" in contents
    assert "第二段内容" in contents


def test_ingest_source_no_chunks_creates_single_node(empty_graph, mock_llm):
    """无 chunks 时整条 source 作为一个节点。"""
    wp = _make_pipeline(empty_graph, mock_llm)
    result = wp.ingest_source(SourceData(name="note.md", source_type="file"))
    assert len(result) == 1


def test_ingest_source_links_to_targets(empty_graph, mock_llm):
    """source 节点对 target_ids 创建关联边。"""
    concept = Node(id="c1", name="AI", content="", node_class=CLASS_CONCEPT)
    empty_graph.add_node(concept)

    wp = _make_pipeline(empty_graph, mock_llm)
    result = wp.ingest_source(
        SourceData(name="ai_paper.pdf", source_type="file", target_ids=["c1"])
    )
    assert len(result) == 1
    source = result[0]
    # source → concept 应有关联边
    assoc_edges = [
        e for e in empty_graph.get_edges_between(source.id, "c1")
        if e.type == EDGE_ASSOC
    ]
    assert len(assoc_edges) >= 1


def test_ingest_source_skips_nonexistent_targets(empty_graph, mock_llm):
    """target_ids 中不存在的节点被跳过（不报错、不建悬空边）。"""
    wp = _make_pipeline(empty_graph, mock_llm)
    result = wp.ingest_source(
        SourceData(name="doc.pdf", source_type="file", target_ids=["ghost_id"])
    )
    assert len(result) == 1
    # 无悬空边
    assert len(empty_graph.get_all_edges()) == 0


def test_ingest_source_extensions_has_source_meta(empty_graph, mock_llm):
    """source 节点 extensions 包含 source_meta（source_type / chunk / targets）。"""
    wp = _make_pipeline(empty_graph, mock_llm)
    result = wp.ingest_source(
        SourceData(
            name="data.csv",
            source_type="file",
            chunks=[{"content": "row1", "chunk_index": 0}],
            target_ids=[],
        )
    )
    source = result[0]
    assert "source_meta" in source.extensions
    meta = source.extensions["source_meta"]
    assert meta["source_type"] == "file"
    assert meta["chunk"]["chunk_index"] == 0
    assert meta["targets"] == []


def test_ingest_source_preserves_custom_extensions(empty_graph, mock_llm):
    """用户自定义 extensions 与 source_meta 共存。"""
    wp = _make_pipeline(empty_graph, mock_llm)
    result = wp.ingest_source(
        SourceData(
            name="log.txt",
            source_type="file",
            extensions={"custom_field": "custom_value"},
        )
    )
    source = result[0]
    assert source.extensions["custom_field"] == "custom_value"
    assert "source_meta" in source.extensions

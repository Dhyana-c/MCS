"""mcs.rendering 公开纯函数测试（result-rendering capability）。

覆盖 ``render_query_result``（str 透传 / Subgraph 经 ContextRenderer.render_facts /
非 str 兜底）与 ``format_ingest_status``（概念 / 节点计数 + persisted、空字段安全、
不含边计数）。逻辑逐字迁自原 MCP server 私有函数，行为不变。
"""

from __future__ import annotations

from mcs.entities.graph import Edge, Node, Subgraph
from mcs.rendering import format_ingest_status, render_query_result


_UNSET = object()


class _FakeWriteContext:
    """WriteContext 替身：仅暴露 format_ingest_status 读取的字段。

    用 ``_UNSET`` 哨兵区分"未传（用默认）"与"显式传 None / []"（测空字段兜底）。
    """

    def __init__(self, changed=_UNSET, concepts=_UNSET, persisted=False) -> None:
        self.changed = [object(), object()] if changed is _UNSET else changed
        self.concepts = [object()] if concepts is _UNSET else concepts
        self.persisted = persisted


# === render_query_result ===


def test_render_str_passthrough():
    assert render_query_result("plain text", "property_graph", None) == "plain text"


def test_render_subgraph_renders_nodes_and_content():
    n = Node(id="a", name="深度学习", content="一种方法")
    out = render_query_result(Subgraph(focus_id="a", nodes=[n]), "property_graph", None)
    assert "深度学习" in out
    assert "一种方法" in out


def test_render_subgraph_with_relation_edges():
    """Subgraph 含关系边（property_graph fact 边）时端点出现在渲染文本中。"""
    a = Node(id="a", name="小明", content="")
    b = Node(id="b", name="苹果", content="")
    e = Edge(id="e1", source_id="a", target_id="b", kind="fact", label="喜欢")
    out = render_query_result(
        Subgraph(focus_id="a", nodes=[a, b], edges=[e]), "property_graph", None
    )
    assert "小明" in out and "苹果" in out


def test_render_other_falls_back_to_str():
    assert render_query_result(12345, "property_graph", None) == "12345"


# === format_ingest_status ===


def test_format_counts_and_no_edges():
    s = format_ingest_status(_FakeWriteContext(persisted=True))
    assert "概念 1" in s
    assert "节点 +2" in s
    assert "persisted=yes" in s
    assert "边" not in s  # MUST NOT 报边计数


def test_format_persisted_no():
    s = format_ingest_status(_FakeWriteContext(changed=[], concepts=[], persisted=False))
    assert "persisted=no" in s
    assert "概念 0" in s
    assert "节点 +0" in s


def test_format_empty_fields_safe():
    """changed / concepts 为 None 时 getattr 兜底，MUST NOT 抛。"""
    s = format_ingest_status(_FakeWriteContext(changed=None, concepts=None))
    assert "概念 0" in s
    assert "节点 +0" in s

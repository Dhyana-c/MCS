"""mcs.rendering 公开纯函数测试（result-rendering capability）。

覆盖 ``format_ingest_status``（概念 / 节点计数 + persisted、空字段安全、不含边计数）。
原 ``render_query_result`` 已随读查询编排退役删除（见 retire-framework-query-pipeline）。
"""

from __future__ import annotations

from mcs.rendering import format_ingest_status


_UNSET = object()


class _FakeWriteContext:
    """WriteContext 替身：仅暴露 format_ingest_status 读取的字段。

    用 ``_UNSET`` 哨兵区分"未传（用默认）"与"显式传 None / []"（测空字段兜底）。
    """

    def __init__(self, changed=_UNSET, concepts=_UNSET, persisted=False) -> None:
        self.changed = [object(), object()] if changed is _UNSET else changed
        self.concepts = [object()] if concepts is _UNSET else concepts
        self.persisted = persisted


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

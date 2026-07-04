"""事件时间戳排序工具测试（mcs.utils.timestamps）。

覆盖：naive/aware 混合形态全序、空/非法垫底、Z 后缀、store 层 get_related_events
混合形态时间倒排、_now_iso 与碎片时间戳同形态。
边界：同一真实时刻两种写法等值；非法字符串不抛；无 event_meta 的事件节点。
"""

from __future__ import annotations

from datetime import datetime, timezone

from mcs.core.write_pipeline import _now_iso
from mcs.entities.graph import CLASS_CONCEPT, CLASS_EVENT, Node
from mcs.stores.in_memory import InMemoryStore
from mcs.utils.timestamps import event_sort_key, timestamp_sort_value


def _event(nid: str, ts: str | None) -> Node:
    ext = {"event_meta": {"timestamp": ts}} if ts is not None else {}
    return Node(id=nid, name=nid, content=nid, node_class=CLASS_EVENT, extensions=ext)


class TestTimestampSortValue:
    def test_same_instant_naive_vs_utc_equal(self) -> None:
        """同一真实时刻：本地裸时间与 UTC aware 写法排序值必须相等。"""
        local = datetime.now().replace(microsecond=0)
        utc = local.astimezone(timezone.utc)
        assert timestamp_sort_value(local.isoformat()) == timestamp_sort_value(
            utc.isoformat()
        )

    def test_mixed_forms_total_order(self) -> None:
        """混合形态全序：本地 10:00 必须晚于「本地 09:00 的 UTC 写法」。

        字典序会把 UTC 写法（如 01:00+00:00）排在本地 10:00 之前或之后取决于
        时区符号——修复前 UTC+8 下 recall 倒排错序的根因。
        """
        early_local = datetime.now().replace(hour=9, minute=0, second=0, microsecond=0)
        late_local = early_local.replace(hour=10)
        early_utc_form = early_local.astimezone(timezone.utc).isoformat()
        assert timestamp_sort_value(late_local.isoformat()) > timestamp_sort_value(
            early_utc_form
        )

    def test_z_suffix(self) -> None:
        assert timestamp_sort_value("2026-07-03T06:30:00Z") == timestamp_sort_value(
            "2026-07-03T06:30:00+00:00"
        )

    def test_empty_and_invalid_sink(self) -> None:
        """空 / 非法 → -inf（倒排后垫底），不抛异常。"""
        assert timestamp_sort_value("") == float("-inf")
        assert timestamp_sort_value(None) == float("-inf")
        assert timestamp_sort_value("not-a-date") == float("-inf")
        assert timestamp_sort_value("2026-07-03T06:30:00") > float("-inf")


class TestEventSortKey:
    def test_missing_event_meta(self) -> None:
        node = Node(id="x", name="x", content="x", node_class=CLASS_EVENT)
        key = event_sort_key(node)
        assert key == (float("-inf"), "x")

    def test_id_as_secondary_key(self) -> None:
        a = _event("a", "2026-07-03T09:00:00")
        b = _event("b", "2026-07-03T09:00:00")
        assert event_sort_key(a) < event_sort_key(b)


class TestStoreMixedTimestampOrdering:
    def test_get_related_events_mixed_forms_desc(self) -> None:
        """get_related_events：本地裸时间与 UTC aware 混存时仍按真实时间倒排。"""
        g = InMemoryStore()
        core = Node(id="c", name="概念", content="概念", node_class=CLASS_CONCEPT)
        g.add_node(core)
        base = datetime.now().replace(hour=12, minute=0, second=0, microsecond=0)
        # e_old（本地 10:00，UTC 写法）、e_mid（本地 11:00 裸）、e_new（本地 12:00 裸）
        e_old = _event("e_old", base.replace(hour=10).astimezone(timezone.utc).isoformat())
        e_mid = _event("e_mid", base.replace(hour=11).isoformat())
        e_new = _event("e_new", base.isoformat())
        for e in (e_old, e_mid, e_new):
            g.add_node(e)
            g.add_edge(e.id, "c")
        got = [n.id for n in g.get_related_events("c")]
        assert got == ["e_new", "e_mid", "e_old"]

    def test_get_related_events_no_timestamp_sinks_last(self) -> None:
        g = InMemoryStore()
        core = Node(id="c", name="概念", content="概念", node_class=CLASS_CONCEPT)
        g.add_node(core)
        e1 = _event("e1", "2026-07-03T09:00:00")
        e2 = _event("e2", None)
        for e in (e1, e2):
            g.add_node(e)
            g.add_edge(e.id, "c")
        got = [n.id for n in g.get_related_events("c")]
        assert got == ["e1", "e2"]


class TestNowIso:
    def test_local_naive_seconds(self) -> None:
        """_now_iso：本地裸时间、秒级——与碎片时间戳（YYYY-MM-DDTHH:MM:SS）同形态。"""
        ts = _now_iso()
        assert "+" not in ts and "Z" not in ts
        parsed = datetime.fromisoformat(ts)
        assert parsed.tzinfo is None
        assert parsed.microsecond == 0

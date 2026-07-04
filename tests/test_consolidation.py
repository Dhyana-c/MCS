"""整合管线测试（确认即 ingest）。

覆盖：ConsolidationTracker（观测、无锁定）、Consolidator.confirm_one / consolidate、
并发 CAS 不重复入图、ConsolidationScheduler。
边界：空 pending / 幂等可重入 / 单条失败容错续跑 / 事件时间忠实 / 互斥 running。
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from mcs_mem.consolidation import ConsolidationTracker, Consolidator
from mcs_mem.fragments import Fragment, FragmentNotFound, FragmentStore


def _seed(frag_dir: Path, date: str, frags: list[Fragment]) -> None:
    frag_dir.mkdir(parents=True, exist_ok=True)
    (frag_dir / f"{date}.jsonl").write_text(
        "".join(f.to_json_line() + "\n" for f in frags), encoding="utf-8"
    )


def _pending(date: str, *items: tuple[str, str]) -> list[Fragment]:
    """构造 pending 碎片列表：items 为 (time, content)。"""
    return [
        Fragment(id=f"{date}T{t}:00", date=date, time=t, content=c, status="pending")
        for t, c in items
    ]


# === ConsolidationTracker（观测、无锁定） ===


class TestConsolidationTracker:
    def test_default_empty(self, tmp_path: Path) -> None:
        tracker = ConsolidationTracker(path=tmp_path / "s.json")
        s = tracker.get("2026-06-27")
        assert s.confirmed == 0 and s.failed == 0 and s.last_run == ""

    def test_record_and_get(self, tmp_path: Path) -> None:
        tracker = ConsolidationTracker(path=tmp_path / "s.json")
        tracker.record("2026-06-27", confirmed=3, failed=1)
        s = tracker.get("2026-06-27")
        assert s.confirmed == 3 and s.failed == 1 and s.last_run

    def test_record_overwrites(self, tmp_path: Path) -> None:
        tracker = ConsolidationTracker(path=tmp_path / "s.json")
        tracker.record("2026-06-27", confirmed=1, failed=2)
        tracker.record("2026-06-27", confirmed=5, failed=0)
        s = tracker.get("2026-06-27")
        assert s.confirmed == 5 and s.failed == 0

    def test_persist_reload(self, tmp_path: Path) -> None:
        path = tmp_path / "s.json"
        ConsolidationTracker(path=path).record("2026-06-27", confirmed=7, failed=0)
        s = ConsolidationTracker(path=path).get("2026-06-27")
        assert s.confirmed == 7

    def test_get_all(self, tmp_path: Path) -> None:
        tracker = ConsolidationTracker(path=tmp_path / "s.json")
        tracker.record("2026-06-25", confirmed=2, failed=0)
        tracker.record("2026-06-27", confirmed=5, failed=0)
        assert {s.date for s in tracker.get_all()} == {"2026-06-25", "2026-06-27"}


# === Consolidator ===


def _make(tmp_path: Path):
    store = FragmentStore(fragments_dir=tmp_path / "fragments")
    mem = MagicMock()
    mem.ingest_structured.side_effect = [f"ev_{i}" for i in range(1, 100)]
    tracker = ConsolidationTracker(path=tmp_path / "cons.json")
    return Consolidator(fragment_store=store, memory=mem, tracker=tracker), store, mem, tracker


class TestConfirmOne:
    def test_confirm_pending(self, tmp_path: Path) -> None:
        c, store, mem, _ = _make(tmp_path)
        _seed(tmp_path / "fragments", "2026-06-27", _pending("2026-06-27", ("09:00", "消息A")))
        store = c._fragments
        fid = store.read_all("2026-06-27")[0].id
        res = c.confirm_one(fid)
        assert res["status"] == "confirmed" and res["event_id"] == "ev_1"
        f = store.get(fid)
        assert f.status == "confirmed" and f.event_id == "ev_1"
        mem.ingest_structured.assert_called_once()

    def test_confirm_already_idempotent(self, tmp_path: Path) -> None:
        c, _, mem, _ = _make(tmp_path)
        store = c._fragments
        _seed(tmp_path / "fragments", "2026-06-27", _pending("2026-06-27", ("09:00", "A")))
        fid = store.read_all("2026-06-27")[0].id
        c.confirm_one(fid)
        mem.ingest_structured.reset_mock()
        res = c.confirm_one(fid)  # 已 confirmed
        assert res.get("already") is True
        mem.ingest_structured.assert_not_called()

    def test_ingest_failure_aborts_and_raises(self, tmp_path: Path) -> None:
        store = FragmentStore(fragments_dir=tmp_path / "fragments")
        mem = MagicMock()
        mem.ingest_structured.side_effect = RuntimeError("ingest down")
        tracker = ConsolidationTracker(path=tmp_path / "c.json")
        c = Consolidator(fragment_store=store, memory=mem, tracker=tracker)
        _seed(tmp_path / "fragments", "2026-06-27", _pending("2026-06-27", ("09:00", "A")))
        fid = store.read_all("2026-06-27")[0].id
        with pytest.raises(RuntimeError, match="ingest down"):
            c.confirm_one(fid)
        # 回退 pending、event_id 仍 None（可重试）
        f = store.get(fid)
        assert f.status == "pending" and f.event_id is None

    def test_confirm_missing_raises(self, tmp_path: Path) -> None:
        c, _, _, _ = _make(tmp_path)
        with pytest.raises(FragmentNotFound):
            c.confirm_one("2099-01-01T00:00:00")

    def test_event_timestamp_is_fragment_time(self, tmp_path: Path) -> None:
        c, _, mem, _ = _make(tmp_path)
        store = c._fragments
        _seed(tmp_path / "fragments", "2026-06-27", _pending("2026-06-27", ("14:30", "内容")))
        fid = store.read_all("2026-06-27")[0].id
        c.confirm_one(fid)
        assert mem.ingest_structured.call_args[0][1] == "2026-06-27T14:30:00"
        assert mem.ingest_structured.call_args[0][0] == "内容"  # 正文，无时间前缀

    def test_uses_current_content_after_cas(self, tmp_path: Path) -> None:
        """TOCTOU 防护：begin_confirm 前的并发编辑后，ingest 用 CAS 后的当前内容（非旧快照）。"""

        class _EditingStore(FragmentStore):
            def begin_confirm(self, frag_id: str) -> bool:
                # 模拟「初次读取 → begin_confirm」窗口内的并发编辑（碎片仍 pending）
                self.update(frag_id, "编辑后")
                return super().begin_confirm(frag_id)

        store = _EditingStore(fragments_dir=tmp_path / "fragments")
        _seed(tmp_path / "fragments", "2026-06-27", _pending("2026-06-27", ("09:00", "原始")))
        fid = store.read_all("2026-06-27")[0].id
        mem = MagicMock()
        mem.ingest_structured.return_value = "ev_1"
        tracker = ConsolidationTracker(path=tmp_path / "c.json")
        c = Consolidator(fragment_store=store, memory=mem, tracker=tracker)
        c.confirm_one(fid)
        # ingest 的是 CAS 后冻结的当前内容，而非旧快照"原始"
        assert mem.ingest_structured.call_args[0][0] == "编辑后"
        assert store.get(fid).content == "编辑后"


class TestConsolidate:
    def test_n_pending_n_events(self, tmp_path: Path) -> None:
        c, _, mem, tracker = _make(tmp_path)
        _seed(tmp_path / "fragments", "2026-06-27",
              _pending("2026-06-27", ("09:00", "A"), ("10:00", "B"), ("11:00", "C")))
        res = c.consolidate("2026-06-27")
        assert res == {"ok": True, "date": "2026-06-27", "confirmed": 3, "skipped": 0, "failed": 0}
        assert mem.ingest_structured.call_count == 3
        assert tracker.get("2026-06-27").confirmed == 3

    def test_empty_no_ingest(self, tmp_path: Path) -> None:
        c, _, mem, _ = _make(tmp_path)
        res = c.consolidate("2099-01-01")
        assert res["confirmed"] == 0 and res["skipped"] == 0 and res["failed"] == 0
        mem.ingest_structured.assert_not_called()

    def test_skipped_counts_already_confirmed(self, tmp_path: Path) -> None:
        c, _, mem, _ = _make(tmp_path)
        store = c._fragments
        _seed(tmp_path / "fragments", "2026-06-27", [
            Fragment(id="2026-06-27T09:00:00", date="2026-06-27", time="09:00", content="A", status="confirmed", event_id="ev_x"),
            Fragment(id="2026-06-27T10:00:00", date="2026-06-27", time="10:00", content="B", status="pending"),
        ])
        res = c.consolidate("2026-06-27")
        assert res["confirmed"] == 1 and res["skipped"] == 1 and res["failed"] == 0

    def test_idempotent_rerun_no_double_ingest(self, tmp_path: Path) -> None:
        c, _, mem, _ = _make(tmp_path)
        _seed(tmp_path / "fragments", "2026-06-27", _pending("2026-06-27", ("09:00", "A"), ("10:00", "B")))
        c.consolidate("2026-06-27")
        mem.ingest_structured.reset_mock()
        res2 = c.consolidate("2026-06-27")  # 无单日锁定，但全 confirmed → skipped
        assert res2["confirmed"] == 0 and res2["skipped"] == 2
        mem.ingest_structured.assert_not_called()

    def test_no_single_day_lock_new_pending_confirmable(self, tmp_path: Path) -> None:
        """无单日锁定：整合后当天再记的 pending 可再次整合入图。"""
        c, _, mem, _ = _make(tmp_path)
        store = c._fragments
        _seed(tmp_path / "fragments", "2026-06-27", _pending("2026-06-27", ("09:00", "A")))
        c.consolidate("2026-06-27")  # 确认 A
        # 追加新 pending（同日，直接写入模拟当天后续 /note）
        _seed(tmp_path / "fragments", "2026-06-27", store.read_all("2026-06-27") + _pending("2026-06-27", ("12:00", "B")))
        # 启动清理不涉入；重读
        store2 = FragmentStore(fragments_dir=tmp_path / "fragments")
        c2 = Consolidator(fragment_store=store2, memory=mem, tracker=c.tracker)
        res = c2.consolidate("2026-06-27")
        assert res["confirmed"] == 1 and res["skipped"] == 1  # 仅新 B 入图、A 跳过

    def test_single_failure_continues(self, tmp_path: Path) -> None:
        store = FragmentStore(fragments_dir=tmp_path / "fragments")
        mem = MagicMock()
        mem.ingest_structured.side_effect = ["ev1", RuntimeError("x"), "ev3"]
        tracker = ConsolidationTracker(path=tmp_path / "c.json")
        c = Consolidator(fragment_store=store, memory=mem, tracker=tracker)
        _seed(tmp_path / "fragments", "2026-06-27",
              _pending("2026-06-27", ("09:00", "A"), ("10:00", "B"), ("11:00", "C")))
        res = c.consolidate("2026-06-27")
        assert res["confirmed"] == 2 and res["failed"] == 1
        # 失败那条回退 pending、可重试
        statuses = {f.content: f.status for f in store.read_all("2026-06-27")}
        assert statuses == {"A": "confirmed", "B": "pending", "C": "confirmed"}
        assert tracker.get("2026-06-27").failed == 1

    def test_failed_retry_only_pending(self, tmp_path: Path) -> None:
        store = FragmentStore(fragments_dir=tmp_path / "fragments")
        mem = MagicMock()
        mem.ingest_structured.side_effect = ["ev1", RuntimeError("x"), "ev3"]
        tracker = ConsolidationTracker(path=tmp_path / "c.json")
        c = Consolidator(fragment_store=store, memory=mem, tracker=tracker)
        _seed(tmp_path / "fragments", "2026-06-27",
              _pending("2026-06-27", ("09:00", "A"), ("10:00", "B"), ("11:00", "C")))
        c.consolidate("2026-06-27")  # B 失败
        mem.ingest_structured.reset_mock()
        mem.ingest_structured.side_effect = None
        mem.ingest_structured.return_value = "ev2"
        res2 = c.consolidate("2026-06-27")
        assert mem.ingest_structured.call_count == 1  # 仅 B（A、C 已 confirmed 跳过）
        assert res2["confirmed"] == 1 and res2["skipped"] == 2
        assert all(f.status == "confirmed" for f in store.read_all("2026-06-27"))

    def test_mutex_running(self, tmp_path: Path) -> None:
        c, _, _, _ = _make(tmp_path)
        c._mutex.acquire()
        try:
            res = c.consolidate("2026-06-27")
            assert res["ok"] is False and res.get("warning")
        finally:
            c._mutex.release()


class TestConcurrentCAS:
    """并发确认同一条碎片：仅一个 ingest，其余抢占失败、不重复入图。"""

    def test_concurrent_confirm_single_ingest(self, tmp_path: Path) -> None:
        store = FragmentStore(fragments_dir=tmp_path / "fragments")
        _seed(tmp_path / "fragments", "2026-06-27", _pending("2026-06-27", ("09:00", "并发")))
        fid = store.read_all("2026-06-27")[0].id

        class _SlowMem:
            def __init__(self) -> None:
                self.calls: list[tuple[str, str]] = []
                self.lock = threading.Lock()

            def ingest_structured(self, content: str, ts: str) -> str:
                with self.lock:
                    self.calls.append((content, ts))
                    n = len(self.calls)
                time.sleep(0.02)  # 拉宽竞态窗口
                return f"ev_{n}"

        mem = _SlowMem()
        tracker = ConsolidationTracker(path=tmp_path / "c.json")
        c = Consolidator(fragment_store=store, memory=mem, tracker=tracker)

        results: list[object] = []
        rlock = threading.Lock()

        def _worker() -> None:
            try:
                r = c.confirm_one(fid)
            except Exception as e:  # pragma: no cover
                r = e
            with rlock:
                results.append(r)

        threads = [threading.Thread(target=_worker) for _ in range(8)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(mem.calls) == 1  # 仅一次 ingest
        confirmed = [r for r in results if isinstance(r, dict) and not r.get("already")]
        already = [r for r in results if isinstance(r, dict) and r.get("already")]
        assert len(confirmed) == 1 and len(already) == 7
        assert store.get(fid).status == "confirmed"


# === ConsolidationScheduler ===


class TestConsolidationScheduler:
    def test_parse_cron(self) -> None:
        from mcs_mem.scheduler import ConsolidationScheduler

        assert ConsolidationScheduler._parse_cron("30 0 * * *") == {
            "minute": "30", "hour": "0", "day": "*", "month": "*", "day_of_week": "*",
        }

    def test_parse_cron_invalid(self) -> None:
        from mcs_mem.scheduler import ConsolidationScheduler

        with pytest.raises(ValueError, match="无效"):
            ConsolidationScheduler._parse_cron("30 0 *")

    def test_disabled(self) -> None:
        from mcs_mem.scheduler import ConsolidationScheduler

        s = ConsolidationScheduler(consolidator=MagicMock(), enabled=False)
        s.start()
        assert s._scheduler is None

    def test_start_shutdown(self) -> None:
        pytest.importorskip("apscheduler")
        from mcs_mem.scheduler import ConsolidationScheduler

        s = ConsolidationScheduler(consolidator=MagicMock(), cron="0 1 * * *")
        s.start()
        assert s._scheduler is not None
        s.shutdown()

    def test_run_yesterday(self) -> None:
        from datetime import date as date_type, timedelta

        from mcs_mem.scheduler import ConsolidationScheduler

        mock = MagicMock()
        mock.consolidate.return_value = {
            "ok": True, "date": "2026-06-26", "confirmed": 3, "skipped": 0, "failed": 0,
        }
        ConsolidationScheduler(consolidator=mock)._run_yesterday()
        yesterday = (date_type.today() - timedelta(days=1)).isoformat()
        mock.consolidate.assert_called_once_with(yesterday)


# === 重复入图自愈 + tracker 封装 ===


class TestConfirmOneSelfHeal:
    """attach_event 后 confirm_mark 失败：保留 confirming+event_id（不清锚点、防重复入图）。"""

    def test_attach_then_confirm_mark_fail_keeps_event_id(self, tmp_path: Path) -> None:
        store = FragmentStore(fragments_dir=tmp_path / "fragments")
        mem = MagicMock()
        mem.ingest_structured.return_value = "ev_1"
        c = Consolidator(
            fragment_store=store,
            memory=mem,
            tracker=ConsolidationTracker(path=tmp_path / "c.json"),
        )
        _seed(tmp_path / "fragments", "2026-06-27", _pending("2026-06-27", ("09:00", "A")))
        fid = store.read_all("2026-06-27")[0].id
        # 模拟 attach_event 已成功落 event_id 后、confirm_mark 崩（本地写故障）
        store.confirm_mark = MagicMock(side_effect=OSError("disk"))
        with pytest.raises(OSError):
            c.confirm_one(fid)
        f = store.get(fid)
        # event_id 已落（ingest 成功）、状态仍 confirming（未 abort）——重启 _cleanup_confirming 自愈 confirmed
        assert f.status == "confirming" and f.event_id == "ev_1"
        mem.ingest_structured.assert_called_once()


class TestTrackerProperty:
    def test_tracker_property_exposes_tracker(self, tmp_path: Path) -> None:
        c, _, _, tracker = _make(tmp_path)
        assert c.tracker is tracker  # 公共 property 返回同一 tracker（路由层不再探 _tracker）


class TestAttachEventFailure:
    """attach_event 抛错（本地 IO 故障）：事件已建，MUST NOT abort（防重复入图）。"""

    def test_attach_fail_confirm_mark_succeeds(self, tmp_path: Path) -> None:
        """attach 失败但 confirm_mark 成功：最终 confirmed + event_id 完整、单次 ingest。"""
        store = FragmentStore(fragments_dir=tmp_path / "fragments")
        mem = MagicMock()
        mem.ingest_structured.return_value = "ev_1"
        c = Consolidator(
            fragment_store=store,
            memory=mem,
            tracker=ConsolidationTracker(path=tmp_path / "c.json"),
        )
        _seed(tmp_path / "fragments", "2026-06-27", _pending("2026-06-27", ("09:00", "A")))
        fid = store.read_all("2026-06-27")[0].id
        store.attach_event = MagicMock(side_effect=OSError("disk"))
        res = c.confirm_one(fid)
        assert res["status"] == "confirmed" and res["event_id"] == "ev_1"
        f = store.get(fid)
        assert f.status == "confirmed" and f.event_id == "ev_1"
        mem.ingest_structured.assert_called_once()

    def test_attach_and_mark_both_fail_no_abort(self, tmp_path: Path) -> None:
        """attach 与 confirm_mark 均失败：不 abort（修复前误判「事件未建」回退 pending
        → 重试重复入图）；状态留 confirming、单次 ingest。"""
        store = FragmentStore(fragments_dir=tmp_path / "fragments")
        mem = MagicMock()
        mem.ingest_structured.return_value = "ev_1"
        c = Consolidator(
            fragment_store=store,
            memory=mem,
            tracker=ConsolidationTracker(path=tmp_path / "c.json"),
        )
        _seed(tmp_path / "fragments", "2026-06-27", _pending("2026-06-27", ("09:00", "A")))
        fid = store.read_all("2026-06-27")[0].id
        store.attach_event = MagicMock(side_effect=OSError("disk"))
        store.confirm_mark = MagicMock(side_effect=OSError("disk"))
        with pytest.raises(OSError):
            c.confirm_one(fid)
        f = store.get(fid)
        assert f.status == "confirming"  # 未回退 pending → 不会重 ingest
        mem.ingest_structured.assert_called_once()


class TestFragmentTimestampSeconds:
    """碎片入图事件时间：优先取 id 中的秒级时间（同一分钟多条保真实次序）。"""

    def test_seconds_from_id(self, tmp_path: Path) -> None:
        c, _, mem, _ = _make(tmp_path)
        store = c._fragments
        frag = Fragment(
            id="2026-06-27T09:00:33",
            date="2026-06-27",
            time="09:00",
            content="秒级",
            status="pending",
        )
        _seed(tmp_path / "fragments", "2026-06-27", [frag])
        c.confirm_one(frag.id)
        assert mem.ingest_structured.call_args[0][1] == "2026-06-27T09:00:33"

    def test_seconds_from_id_with_conflict_suffix(self, tmp_path: Path) -> None:
        """同秒冲突后缀 ``-2`` 不进时间戳。"""
        c, _, mem, _ = _make(tmp_path)
        frag = Fragment(
            id="2026-06-27T09:00:33-2",
            date="2026-06-27",
            time="09:00",
            content="冲突后缀",
            status="pending",
        )
        _seed(tmp_path / "fragments", "2026-06-27", [frag])
        c.confirm_one(frag.id)
        assert mem.ingest_structured.call_args[0][1] == "2026-06-27T09:00:33"

    def test_fallback_minute_precision(self, tmp_path: Path) -> None:
        """id 形态异常（老数据）→ 退回 time 补 :00 的旧口径。"""
        from mcs_mem.consolidation import _fragment_timestamp

        frag = Fragment(
            id="legacy-id", date="2026-06-27", time="14:30", content="旧", status="pending"
        )
        assert _fragment_timestamp(frag) == "2026-06-27T14:30:00"


class TestSchedulerInvalidCron:
    def test_invalid_cron_disables_not_crashes(self) -> None:
        """非法 cron（env 配错）：start() 不抛、定时禁用（不炸 app lifespan）。"""
        from mcs_mem.scheduler import ConsolidationScheduler

        s = ConsolidationScheduler(consolidator=MagicMock(), cron="bad cron expr")
        s.start()  # 不应 raise
        assert s._scheduler is None
        s.shutdown()  # 幂等无害

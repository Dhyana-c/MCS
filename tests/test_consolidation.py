"""整合管线测试（Slice 2）。

覆盖：parse_fragments、ConsolidationTracker、Consolidator 整合主流程。
边界情况：空碎片 / 单日锁定 / 去噪 / 单条失败容错 / 互斥 running。
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from mcs_mem.consolidation import (
    ConsolidationStatus,
    ConsolidationTracker,
    Consolidator,
    parse_fragments,
)


# === parse_fragments ===


class TestParseFragments:
    def test_normal_multi_line(self) -> None:
        """正常多行解析。"""
        md = "09:00 早上讨论了架构\n14:30 下午写了代码"
        result = parse_fragments(md, "2026-06-27")
        assert len(result) == 2
        assert result[0] == ("2026-06-27T09:00:00", "早上讨论了架构")
        assert result[1] == ("2026-06-27T14:30:00", "下午写了代码")

    def test_skip_malformed_line(self) -> None:
        """格式错误行跳过。"""
        md = "09:00 正确行\n这是一段描述没有时间\n10:00 另一正确行"
        result = parse_fragments(md, "2026-06-27")
        assert len(result) == 2

    def test_empty_content_skipped(self) -> None:
        """空内容行跳过。"""
        md = "09:00    \n10:00 有内容"
        result = parse_fragments(md, "2026-06-27")
        assert len(result) == 1
        assert result[0][1] == "有内容"

    def test_chinese_and_special_chars(self) -> None:
        """中文和特殊字符。"""
        md = "14:30 学习了《深度学习》🎉"
        result = parse_fragments(md, "2026-06-27")
        assert len(result) == 1
        assert "《深度学习》🎉" in result[0][1]

    def test_content_no_time_prefix(self) -> None:
        """content 不含时间前缀。"""
        md = "14:30 今天完成了设计文档"
        result = parse_fragments(md, "2026-06-27")
        assert result[0][1] == "今天完成了设计文档"
        assert "14:30" not in result[0][1]

    def test_empty_input(self) -> None:
        """空输入返回空列表。"""
        assert parse_fragments("", "2026-06-27") == []
        assert parse_fragments("\n\n", "2026-06-27") == []


# === ConsolidationTracker ===


class TestConsolidationTracker:
    def test_initial_pending(self, tmp_path: Path) -> None:
        """未整合日期返回 pending。"""
        tracker = ConsolidationTracker(path=tmp_path / "status.json")
        s = tracker.get("2026-06-27")
        assert s.status == "pending"

    def test_set_running(self, tmp_path: Path) -> None:
        """设为 running。"""
        tracker = ConsolidationTracker(path=tmp_path / "status.json")
        assert tracker.set_running("2026-06-27") is True
        assert tracker.get("2026-06-27").status == "running"

    def test_set_done(self, tmp_path: Path) -> None:
        """设为 done + 事件数。"""
        tracker = ConsolidationTracker(path=tmp_path / "status.json")
        tracker.set_running("2026-06-27")
        tracker.set_done("2026-06-27", 5)
        s = tracker.get("2026-06-27")
        assert s.status == "done"
        assert s.events == 5

    def test_done_locks_reentry(self, tmp_path: Path) -> None:
        """done 后 set_running 返回 False（锁定）。"""
        tracker = ConsolidationTracker(path=tmp_path / "status.json")
        tracker.set_running("2026-06-27")
        tracker.set_done("2026-06-27", 3)
        assert tracker.set_running("2026-06-27") is False

    def test_running_locks_reentry(self, tmp_path: Path) -> None:
        """running 时 set_running 返回 False。"""
        tracker = ConsolidationTracker(path=tmp_path / "status.json")
        tracker.set_running("2026-06-27")
        assert tracker.set_running("2026-06-27") is False

    def test_persist_and_reload(self, tmp_path: Path) -> None:
        """持久化后重启恢复。"""
        path = tmp_path / "status.json"
        tracker = ConsolidationTracker(path=path)
        tracker.set_running("2026-06-27")
        tracker.set_done("2026-06-27", 7)
        # 新 tracker 加载同一文件
        tracker2 = ConsolidationTracker(path=path)
        s = tracker2.get("2026-06-27")
        assert s.status == "done"
        assert s.events == 7

    def test_set_failed(self, tmp_path: Path) -> None:
        """设为 failed。"""
        tracker = ConsolidationTracker(path=tmp_path / "status.json")
        tracker.set_running("2026-06-27")
        tracker.set_failed("2026-06-27")
        assert tracker.get("2026-06-27").status == "failed"

    def test_get_all(self, tmp_path: Path) -> None:
        """获取所有日期状态。"""
        tracker = ConsolidationTracker(path=tmp_path / "status.json")
        tracker.set_running("2026-06-25")
        tracker.set_done("2026-06-25", 2)
        tracker.set_running("2026-06-27")
        tracker.set_done("2026-06-27", 5)
        all_statuses = tracker.get_all()
        dates = {s.date for s in all_statuses}
        assert "2026-06-25" in dates
        assert "2026-06-27" in dates


# === Consolidator 整合主流程 ===


def _make_consolidator(
    tmp_path: Path,
    fragments_content: str | None = None,
    denoiser=None,
):
    """构造 Consolidator + mock 依赖。"""
    from mcs_mem.fragments import FragmentStore

    frag_dir = tmp_path / "fragments"
    frag_store = FragmentStore(fragments_dir=frag_dir)
    if fragments_content is not None:
        frag_store.overwrite("2026-06-27", fragments_content)

    mock_memory = MagicMock()
    mock_memory.ingest_structured.return_value = "ev_test_id"

    tracker = ConsolidationTracker(path=tmp_path / "consolidation_status.json")
    consolidator = Consolidator(
        fragment_store=frag_store,
        memory=mock_memory,
        tracker=tracker,
        denoiser=denoiser,
    )
    return consolidator, mock_memory, tracker


class TestConsolidator:
    def test_empty_fragments_no_ingest(self, tmp_path: Path) -> None:
        """空碎片不入图。"""
        c, mock_mem, tracker = _make_consolidator(tmp_path, fragments_content="")
        result = c.consolidate("2026-06-27")
        assert result["status"] == "done"
        assert result["events"] == 0
        mock_mem.ingest_structured.assert_not_called()

    def test_retained_fragments_ingested(self, tmp_path: Path) -> None:
        """保留碎片逐条入图（不合成）。"""
        md = "09:00 消息A\n14:30 消息B"
        c, mock_mem, _ = _make_consolidator(tmp_path, fragments_content=md)
        result = c.consolidate("2026-06-27")
        assert result["status"] == "done"
        assert result["events"] == 2
        assert mock_mem.ingest_structured.call_count == 2

    def test_event_timestamp_matches_fragment(self, tmp_path: Path) -> None:
        """事件时间 = 碎片时间，无塌缩。"""
        md = "14:30 测试内容"
        c, mock_mem, _ = _make_consolidator(tmp_path, fragments_content=md)
        c.consolidate("2026-06-27")
        # 验证 ingest_structured 的 timestamp 参数
        call_args = mock_mem.ingest_structured.call_args
        assert call_args[0][1] == "2026-06-27T14:30:00"

    def test_single_day_lock(self, tmp_path: Path) -> None:
        """单日锁定：done 后再触发返回 already。"""
        md = "09:00 测试"
        c, _, _ = _make_consolidator(tmp_path, fragments_content=md)
        r1 = c.consolidate("2026-06-27")
        assert r1["status"] == "done"
        r2 = c.consolidate("2026-06-27")
        assert r2["status"] == "already"

    def test_single_ingest_failure_marks_failed(self, tmp_path: Path) -> None:
        """单条 ingest 失败：不再掩盖为 done，标 failed + 记录成功条数与已成功 ts。"""
        md = "09:00 消息A\n10:00 消息B\n11:00 消息C"
        c, mock_mem, tracker = _make_consolidator(tmp_path, fragments_content=md)
        # 第二条失败
        mock_mem.ingest_structured.side_effect = [
            "ev1",
            RuntimeError("ingest failed"),
            "ev3",
        ]
        result = c.consolidate("2026-06-27")
        assert result["status"] == "failed"  # 部分失败 → failed（不再掩盖为 done）
        assert result["events"] == 2  # 成功 2 条（A、C）
        assert result["failures"] == 1  # 失败 1 条（B）
        # 持久化已成功碎片 ts（A、C），供重试幂等去重
        st = tracker.get("2026-06-27")
        assert st.status == "failed"
        assert set(st.succeeded_ts) == {"2026-06-27T09:00:00", "2026-06-27T11:00:00"}

    def test_failed_retry_skips_succeeded(self, tmp_path: Path) -> None:
        """failed 重试幂等：跳过已成功碎片、不重复入图；全补齐后标 done。"""
        md = "09:00 消息A\n10:00 消息B\n11:00 消息C"
        c, mock_mem, tracker = _make_consolidator(tmp_path, fragments_content=md)
        # 第一次：B 失败 → failed（A、C 成功）
        mock_mem.ingest_structured.side_effect = ["ev1", RuntimeError("x"), "ev3"]
        r1 = c.consolidate("2026-06-27")
        assert r1["status"] == "failed"
        assert mock_mem.ingest_structured.call_count == 3
        # 重试：B 这次成功。set_running 从 failed 重入、保留 succeeded_ts，
        # 跳过 A、C（已成功），仅对 B 调 ingest_structured → 不重复入图。
        mock_mem.ingest_structured.reset_mock()
        mock_mem.ingest_structured.side_effect = None  # 清上轮耗尽的 side_effect
        mock_mem.ingest_structured.return_value = "ev2"
        r2 = c.consolidate("2026-06-27")
        assert r2["status"] == "done"
        assert mock_mem.ingest_structured.call_count == 1  # 只 B（A、C 被跳过）
        assert r2["events"] == 3  # 全部 3 条成功
        # done 后 succeeded_ts 清空（全成功、无需保留）
        assert tracker.get("2026-06-27").succeeded_ts == []

    def test_failed_retry_still_failing_stays_failed(self, tmp_path: Path) -> None:
        """failed 重试若仍失败：保持 failed，已成功 ts 不丢、不重复入图。"""
        md = "09:00 消息A\n10:00 消息B\n11:00 消息C"
        c, mock_mem, _ = _make_consolidator(tmp_path, fragments_content=md)
        mock_mem.ingest_structured.side_effect = ["ev1", RuntimeError("x"), "ev3"]
        c.consolidate("2026-06-27")  # failed（A、C 成功）
        # 重试：B 仍失败
        mock_mem.ingest_structured.reset_mock()
        mock_mem.ingest_structured.side_effect = RuntimeError("still")
        r2 = c.consolidate("2026-06-27")
        assert r2["status"] == "failed"
        assert mock_mem.ingest_structured.call_count == 1  # 只 B（A、C 跳过）

    def test_mutex_running(self, tmp_path: Path) -> None:
        """互斥锁：运行中再触发返回 running。"""
        c, _, _ = _make_consolidator(tmp_path, fragments_content="")
        # 手动获取互斥锁模拟运行中
        c._mutex.acquire()
        try:
            result = c.consolidate("2026-06-27")
            assert result["status"] == "running"
        finally:
            c._mutex.release()

    def test_denoiser_filters_noise(self, tmp_path: Path) -> None:
        """去噪器过滤噪声碎片。"""
        md = "09:00 喝了杯咖啡\n10:00 完成了架构设计\n11:00 随便聊聊"
        calls = []

        def denoiser(content: str) -> bool:
            calls.append(content)
            return "设计" in content  # 只保留含"设计"的

        c, mock_mem, _ = _make_consolidator(tmp_path, fragments_content=md,
                                             denoiser=denoiser)
        result = c.consolidate("2026-06-27")
        assert result["events"] == 1
        # 验证只 ingest 了保留的碎片
        call_args = mock_mem.ingest_structured.call_args
        assert "架构设计" in call_args[0][0]

    def test_denoiser_does_not_merge(self, tmp_path: Path) -> None:
        """去噪不合成不归并——多条同事各自保留为独立碎片。"""
        md = "09:00 讨论了方案A\n09:30 讨论了方案B"
        c, mock_mem, _ = _make_consolidator(tmp_path, fragments_content=md)
        result = c.consolidate("2026-06-27")
        assert result["events"] == 2  # 两条都保留，不合成

    def test_denoiser_conservative(self, tmp_path: Path) -> None:
        """去噪保守——拿不准就保留。"""
        md = "09:00 模糊内容"
        c, mock_mem, _ = _make_consolidator(tmp_path, fragments_content=md)
        result = c.consolidate("2026-06-27")
        assert result["events"] == 1  # 默认去噪器全保留

    def test_denoise_does_not_rewrite_content(self, tmp_path: Path) -> None:
        """去噪不改写 content：去噪器收到 + 送 ingest 的 content 都是解析原文（无时间前缀），
        去噪只判去留、不参与 content 构造。"""
        md = "09:30 完成了架构设计"
        seen_by_denoiser: list[str] = []

        def denoiser(content: str) -> bool:
            seen_by_denoiser.append(content)
            return True  # 保留

        c, mock_mem, _ = _make_consolidator(tmp_path, fragments_content=md, denoiser=denoiser)
        c.consolidate("2026-06-27")
        # 去噪器收到解析原文（不含时间前缀）
        assert seen_by_denoiser == ["完成了架构设计"]
        # 送 ingest 的 content 也是原文（未被改写 / 润色）
        assert mock_mem.ingest_structured.call_args[0][0] == "完成了架构设计"

    def test_nonexistent_date_treated_as_empty(self, tmp_path: Path) -> None:
        """不存在的日期视为空，不入图。"""
        c, mock_mem, _ = _make_consolidator(tmp_path, fragments_content=None)
        result = c.consolidate("2099-01-01")
        assert result["status"] == "done"
        assert result["events"] == 0


# === LLMDenoiser ===


class _FakeLLMResponse:
    def __init__(self, content: str) -> None:
        self.content = content
        self.tool_calls = None
        self.trace = None


class _FakeDenoiseLLM:
    """模拟 LLM 后端——返回预定义内容。"""

    def __init__(self, response: str = "保留") -> None:
        self._response = response
        self.calls: list[list[dict]] = []

    def chat(self, messages, tools):
        self.calls.append(messages)
        return _FakeLLMResponse(self._response)


class TestLLMDenoiser:
    def test_retain_fragment(self) -> None:
        """LLM 判"保留"——碎片保留。"""
        from mcs_mem.consolidation import LLMDenoiser

        denoiser = LLMDenoiser(llm=_FakeDenoiseLLM("保留"))
        assert denoiser("今天完成了架构设计") is True

    def test_discard_noise(self) -> None:
        """LLM 判"丢弃"——碎片被丢。"""
        from mcs_mem.consolidation import LLMDenoiser

        denoiser = LLMDenoiser(llm=_FakeDenoiseLLM("丢弃"))
        assert denoiser("哈哈") is False

    def test_llm_failure_conservative(self) -> None:
        """LLM 调用失败——保守保留。"""
        from mcs_mem.consolidation import LLMDenoiser

        broken_llm = MagicMock()
        broken_llm.chat.side_effect = RuntimeError("LLM down")
        denoiser = LLMDenoiser(llm=broken_llm)
        assert denoiser("任何内容") is True  # 保守保留

    def test_denoiser_does_not_merge(self, tmp_path: Path) -> None:
        """LLM 去噪不合成不归并——多条各自独立保留。"""
        from mcs_mem.consolidation import LLMDenoiser

        llm = _FakeDenoiseLLM("保留")
        denoiser = LLMDenoiser(llm=llm)
        md = "09:00 讨论了方案A\n09:30 讨论了方案B"
        c, mock_mem, _ = _make_consolidator(tmp_path, fragments_content=md,
                                             denoiser=denoiser)
        result = c.consolidate("2026-06-27")
        assert result["events"] == 2  # 两条都保留，不合成

    def test_agent_learn_not_affected(self, tmp_path: Path) -> None:
        """去噪只作用整合路径，agent 直接 learn 不经去噪。"""
        from mcs_mem.consolidation import LLMDenoiser

        denoiser = LLMDenoiser(llm=_FakeDenoiseLLM("丢弃"))
        # denoiser 判全丢，但这只影响 Consolidator 的整合流程
        # agent 直接调 memory.learn() 不走 Consolidator
        assert denoiser("重要内容") is False  # 去噪器说丢
        # 但 learn 路径完全不经去噪器——这是设计保证，不是代码保证
        # 此测试仅确认去噪器接口本身不影响 learn


# === ConsolidationScheduler ===


class TestConsolidationScheduler:
    def test_parse_cron(self) -> None:
        """cron 表达式正确解析。"""
        from mcs_mem.scheduler import ConsolidationScheduler

        result = ConsolidationScheduler._parse_cron("30 0 * * *")
        assert result == {
            "minute": "30", "hour": "0", "day": "*",
            "month": "*", "day_of_week": "*",
        }

    def test_parse_cron_invalid(self) -> None:
        """无效 cron 表达式抛异常。"""
        from mcs_mem.scheduler import ConsolidationScheduler

        with pytest.raises(ValueError, match="无效"):
            ConsolidationScheduler._parse_cron("30 0 *")

    def test_disabled_scheduler(self) -> None:
        """enabled=False 不启动调度器。"""
        from mcs_mem.scheduler import ConsolidationScheduler

        mock_consolidator = MagicMock()
        scheduler = ConsolidationScheduler(
            consolidator=mock_consolidator, enabled=False,
        )
        scheduler.start()
        # 不注册定时任务——_scheduler 为 None
        assert scheduler._scheduler is None

    def test_start_and_shutdown(self) -> None:
        """启动后可正常关闭。"""
        pytest.importorskip("apscheduler")
        from mcs_mem.scheduler import ConsolidationScheduler

        mock_consolidator = MagicMock()
        scheduler = ConsolidationScheduler(
            consolidator=mock_consolidator, cron="0 1 * * *",
        )
        scheduler.start()
        assert scheduler._scheduler is not None
        scheduler.shutdown()
        # shutdown 后 scheduler 已停

    def test_run_yesterday(self) -> None:
        """_run_yesterday 调 consolidator.consolidate(昨天)。"""
        from mcs_mem.scheduler import ConsolidationScheduler

        from datetime import date as date_type, timedelta

        mock_consolidator = MagicMock()
        mock_consolidator.consolidate.return_value = {
            "ok": True, "date": "2026-06-26", "status": "done", "events": 3,
        }
        scheduler = ConsolidationScheduler(consolidator=mock_consolidator)
        scheduler._run_yesterday()
        yesterday = (date_type.today() - timedelta(days=1)).isoformat()
        mock_consolidator.consolidate.assert_called_once_with(yesterday)

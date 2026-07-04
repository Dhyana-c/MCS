"""日记生成模块测试（读结构化碎片）。

覆盖：DiaryStore、DiaryGenerator（基于 read_all 各态全量碎片）。
边界：空碎片不生成 / 可重生成 / 中文 / LLM 失败 / 空回复 / 超窗分段。
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from mcs_mem.diary import DiaryGenerator, DiaryStore
from mcs_mem.fragments import FragmentStore


# === DiaryStore ===


class TestDiaryStore:
    def test_write_and_read(self, tmp_path: Path) -> None:
        ds = DiaryStore(diaries_dir=tmp_path / "diaries")
        ds.write("2026-06-27", "# 今日日记\n\n讨论了架构。")
        assert "架构" in ds.read("2026-06-27")

    def test_read_nonexistent(self, tmp_path: Path) -> None:
        assert DiaryStore(diaries_dir=tmp_path / "diaries").read("2099-01-01") is None

    def test_overwrite(self, tmp_path: Path) -> None:
        ds = DiaryStore(diaries_dir=tmp_path / "diaries")
        ds.write("2026-06-27", "旧日记")
        ds.write("2026-06-27", "新日记")
        assert "新日记" in ds.read("2026-06-27") and "旧日记" not in ds.read("2026-06-27")

    def test_list_descending(self, tmp_path: Path) -> None:
        ds = DiaryStore(diaries_dir=tmp_path / "diaries")
        for d in ("2026-06-25", "2026-06-27", "2026-06-26"):
            ds.write(d, "x")
        assert ds.list_dates() == ["2026-06-27", "2026-06-26", "2026-06-25"]

    def test_creates_dir(self, tmp_path: Path) -> None:
        ds = DiaryStore(diaries_dir=tmp_path / "a" / "b")
        ds.write("2026-06-27", "测试")
        assert (tmp_path / "a" / "b").is_dir()


# === DiaryGenerator ===


class _FakeLLMResponse:
    def __init__(self, content: str) -> None:
        self.content = content


class _FakeLLM:
    def __init__(self, response: str = "# 日记\n\n今天完成了设计。") -> None:
        self._response = response
        self.calls: list[list[dict]] = []

    def chat(self, messages: list[dict], tools: list[dict]) -> _FakeLLMResponse:
        self.calls.append(messages)
        return _FakeLLMResponse(self._response)


class _FakeFragStore:
    """read_all 返回带 .time / .content 的碎片对象（各态全量、已按 time 排序）。"""

    def __init__(self, items: list[tuple[str, str]]) -> None:
        self._items = items

    def read_all(self, date: str):
        return [SimpleNamespace(time=t, content=c) for t, c in self._items]


def _make_generator(tmp_path: Path, items: list[tuple[str, str]] | None, llm_response: str = "# 日记\n\n完成了设计。"):
    frag_store = _FakeFragStore(items or [])
    diary_store = DiaryStore(diaries_dir=tmp_path / "diaries")
    llm = _FakeLLM(response=llm_response)
    return DiaryGenerator(fragment_store=frag_store, diary_store=diary_store, llm=llm), diary_store, llm


class TestDiaryGenerator:
    def test_generate_from_fragments(self, tmp_path: Path) -> None:
        gen, diary_store, llm = _make_generator(tmp_path, [("09:00", "讨论了架构"), ("14:30", "写了代码")])
        assert gen.generate("2026-06-27") is not None
        assert len(llm.calls) == 1
        assert diary_store.read("2026-06-27") is not None

    def test_all_states_fed_to_llm(self, tmp_path: Path) -> None:
        """read_all 各态全量都进 prompt（pending / confirming / confirmed 不区分）。"""
        gen, _, llm = _make_generator(tmp_path, [("09:00", "待确认事"), ("10:00", "已确认事")])
        gen.generate("2026-06-27")
        user_msg = llm.calls[0][-1]["content"]
        assert "待确认事" in user_msg and "已确认事" in user_msg
        assert "09:00 待确认事" in user_msg  # HH:MM 内容 行格式

    def test_no_fragments_returns_none(self, tmp_path: Path) -> None:
        gen, _, llm = _make_generator(tmp_path, [])
        assert gen.generate("2026-06-27") is None
        assert len(llm.calls) == 0

    def test_regenerable(self, tmp_path: Path) -> None:
        gen, diary_store, _ = _make_generator(tmp_path, [("09:00", "A")], llm_response="第一版")
        gen.generate("2026-06-27")
        assert "第一版" in diary_store.read("2026-06-27")
        gen._llm = _FakeLLM(response="第二版")
        gen.generate("2026-06-27")
        assert "第二版" in diary_store.read("2026-06-27") and "第一版" not in diary_store.read("2026-06-27")

    def test_llm_failure_raises(self, tmp_path: Path) -> None:
        gen, _, _ = _make_generator(tmp_path, [("09:00", "测试")])
        gen._llm = MagicMock()
        gen._llm.chat.side_effect = RuntimeError("LLM down")
        with pytest.raises(RuntimeError, match="LLM down"):
            gen.generate("2026-06-27")

    def test_empty_llm_response_returns_none(self, tmp_path: Path) -> None:
        gen, diary_store, _ = _make_generator(tmp_path, [("09:00", "有内容")], llm_response="")
        assert gen.generate("2026-06-27") is None
        assert diary_store.read("2026-06-27") is None

    def test_chinese(self, tmp_path: Path) -> None:
        gen, _, llm = _make_generator(tmp_path, [("14:30", "学习了《深度学习》")], llm_response="学了深度学习")
        assert gen.generate("2026-06-27") is not None
        assert "深度学习" in llm.calls[0][-1]["content"]

    def test_overwindow_splits_and_merges(self, tmp_path: Path) -> None:
        from mcs_mem.diary import _DIARY_MAX_CHARS

        line = "一条用于撑大单日碎片总量的较长碎片内容测试超窗分段合并逻辑"
        n = (_DIARY_MAX_CHARS // len(line)) + 5
        items = [(f"{i % 24:02d}:{i % 60:02d}", f"{line}{i}") for i in range(n)]
        gen, _, llm = _make_generator(tmp_path, items, llm_response="日记片段")
        assert gen.generate("2026-06-27") is not None
        assert len(llm.calls) > 1  # 分段各一次 + 合并一次

    def test_integration_real_fragment_store(self, tmp_path: Path) -> None:
        """真实 FragmentStore：create 的 pending 碎片喂入日记。"""
        store = FragmentStore(fragments_dir=tmp_path / "fragments")
        _, today, _ = store.create("今天写了测试")
        store.create("还修了个 bug")
        diary_store = DiaryStore(diaries_dir=tmp_path / "diaries")
        llm = _FakeLLM(response="# 日记\n\n今天写测试、修 bug。")
        gen = DiaryGenerator(fragment_store=store, diary_store=diary_store, llm=llm)
        assert gen.generate(today) is not None
        user_msg = llm.calls[0][-1]["content"]
        assert "今天写了测试" in user_msg and "还修了个 bug" in user_msg


class TestMergePromptDate:
    def test_merge_prompt_carries_date(self, tmp_path: Path) -> None:
        """超窗合并阶段的 prompt 必须带 {date} 约束——防 LLM 在合并时杜撰日期/星期。"""
        from mcs_mem.diary import _DIARY_MAX_CHARS

        line = "一条用于撑大单日碎片总量的较长碎片内容测试合并阶段日期注入约束"
        n = (_DIARY_MAX_CHARS // len(line)) + 5
        items = [(f"{i % 24:02d}:{i % 60:02d}", f"{line}{i}") for i in range(n)]
        gen, _, llm = _make_generator(tmp_path, items, llm_response="日记片段")
        gen.generate("2026-06-27")
        merge_msg = llm.calls[-1][-1]["content"]  # 最后一次调用 = 合并
        assert "2026-06-27" in merge_msg

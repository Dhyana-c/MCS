"""日记生成模块测试（Slice 3）。

覆盖：DiaryStore、DiaryGenerator、parse + 概括逻辑。
边界情况：空碎片不生成 / 不杜撰 / 可重生成 / 中文 / LLM 失败。
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from mcs_mem.diary import DiaryGenerator, DiaryStore
from mcs_mem.fragments import FragmentStore


# === DiaryStore ===


class TestDiaryStore:
    def test_write_and_read(self, tmp_path: Path) -> None:
        """写入后可读取。"""
        ds = DiaryStore(diaries_dir=tmp_path / "diaries")
        ds.write("2026-06-27", "# 今日日记\n\n今天讨论了架构。")
        content = ds.read("2026-06-27")
        assert content is not None
        assert "架构" in content

    def test_read_nonexistent(self, tmp_path: Path) -> None:
        """不存在的日期返回 None。"""
        ds = DiaryStore(diaries_dir=tmp_path / "diaries")
        assert ds.read("2099-01-01") is None

    def test_overwrite(self, tmp_path: Path) -> None:
        """覆盖（重生成）后读新内容。"""
        ds = DiaryStore(diaries_dir=tmp_path / "diaries")
        ds.write("2026-06-27", "旧日记")
        ds.write("2026-06-27", "新日记")
        assert "新日记" in ds.read("2026-06-27")
        assert "旧日记" not in ds.read("2026-06-27")

    def test_list_dates_descending(self, tmp_path: Path) -> None:
        """列表按日期倒排。"""
        ds = DiaryStore(diaries_dir=tmp_path / "diaries")
        ds.write("2026-06-25", "A")
        ds.write("2026-06-27", "B")
        ds.write("2026-06-26", "C")
        assert ds.list_dates() == ["2026-06-27", "2026-06-26", "2026-06-25"]

    def test_list_empty(self, tmp_path: Path) -> None:
        """空目录返回空列表。"""
        ds = DiaryStore(diaries_dir=tmp_path / "diaries")
        assert ds.list_dates() == []

    def test_creates_directory(self, tmp_path: Path) -> None:
        """目录不存在时自动创建。"""
        ds = DiaryStore(diaries_dir=tmp_path / "a" / "b")
        ds.write("2026-06-27", "测试")
        assert (tmp_path / "a" / "b").is_dir()


# === DiaryGenerator ===


class _FakeLLMResponse:
    """模拟 LLM 响应（带 .content）。"""

    def __init__(self, content: str) -> None:
        self.content = content


class _FakeLLM:
    """模拟 LLM 后端。"""

    def __init__(self, response_content: str = "# 日记\n\n今天完成了设计。") -> None:
        self._response = response_content
        self.calls: list[list[dict]] = []

    def chat(self, messages: list[dict], tools: list[dict]) -> _FakeLLMResponse:
        self.calls.append(messages)
        return _FakeLLMResponse(self._response)


def _make_generator(
    tmp_path: Path,
    fragments_content: str | None = None,
    llm_response: str = "# 日记\n\n今天完成了设计。",
):
    """构造 DiaryGenerator + 依赖。"""
    frag_store = FragmentStore(fragments_dir=tmp_path / "fragments")
    if fragments_content is not None:
        frag_store.overwrite("2026-06-27", fragments_content)

    diary_store = DiaryStore(diaries_dir=tmp_path / "diaries")
    llm = _FakeLLM(response_content=llm_response)
    generator = DiaryGenerator(
        fragment_store=frag_store,
        diary_store=diary_store,
        llm=llm,
    )
    return generator, frag_store, diary_store, llm


class TestDiaryGenerator:
    def test_generate_from_fragments(self, tmp_path: Path) -> None:
        """有碎片时生成日记。"""
        gen, _, diary_store, llm = _make_generator(
            tmp_path,
            fragments_content="09:00 讨论了架构\n14:30 写了代码",
        )
        result = gen.generate("2026-06-27")
        assert result is not None
        # LLM 被调用
        assert len(llm.calls) == 1
        # 日记已写入
        content = diary_store.read("2026-06-27")
        assert content is not None

    def test_no_fragments_returns_none(self, tmp_path: Path) -> None:
        """无碎片返回 None（不调 LLM）。"""
        gen, _, _, llm = _make_generator(tmp_path, fragments_content="")
        result = gen.generate("2026-06-27")
        assert result is None
        assert len(llm.calls) == 0

    def test_regenerable(self, tmp_path: Path) -> None:
        """可重生成（覆盖旧日记）。"""
        gen, _, diary_store, _ = _make_generator(
            tmp_path,
            fragments_content="09:00 内容A",
            llm_response="第一版日记",
        )
        gen.generate("2026-06-27")
        assert "第一版" in diary_store.read("2026-06-27")

        # 换 LLM 回复重生成
        gen._llm = _FakeLLM(response_content="第二版日记")
        gen.generate("2026-06-27")
        assert "第二版" in diary_store.read("2026-06-27")
        assert "第一版" not in diary_store.read("2026-06-27")

    def test_prompt_includes_fragments(self, tmp_path: Path) -> None:
        """LLM prompt 包含碎片内容。"""
        gen, _, _, llm = _make_generator(
            tmp_path,
            fragments_content="09:00 架构设计讨论",
        )
        gen.generate("2026-06-27")
        # 检查 user message 包含碎片
        user_msg = llm.calls[0][-1]["content"]
        assert "架构设计讨论" in user_msg

    def test_llm_failure_raises(self, tmp_path: Path) -> None:
        """LLM 调用失败抛异常。"""
        gen, _, _, _ = _make_generator(
            tmp_path,
            fragments_content="09:00 测试",
        )
        gen._llm = MagicMock()
        gen._llm.chat.side_effect = RuntimeError("LLM down")
        with pytest.raises(RuntimeError, match="LLM down"):
            gen.generate("2026-06-27")

    def test_nonexistent_date_returns_none(self, tmp_path: Path) -> None:
        """不存在的日期（无碎片文件）返回 None。"""
        gen, _, _, llm = _make_generator(tmp_path, fragments_content=None)
        result = gen.generate("2099-01-01")
        assert result is None
        assert len(llm.calls) == 0

    def test_chinese_fragments(self, tmp_path: Path) -> None:
        """中文碎片正确传入 LLM。"""
        gen, _, _, llm = _make_generator(
            tmp_path,
            fragments_content="14:30 学习了《深度学习》",
            llm_response="今天学习了深度学习",
        )
        result = gen.generate("2026-06-27")
        assert result is not None
        user_msg = llm.calls[0][-1]["content"]
        assert "深度学习" in user_msg

    def test_llm_empty_response_returns_none(self, tmp_path: Path) -> None:
        """LLM 返回空文本时不写日记。"""
        gen, _, diary_store, _ = _make_generator(
            tmp_path,
            fragments_content="09:00 有内容",
            llm_response="",
        )
        result = gen.generate("2026-06-27")
        assert result is None
        assert diary_store.read("2026-06-27") is None

    def test_whitespace_only_fragments_returns_none(self, tmp_path: Path) -> None:
        """纯空白碎片视为空。"""
        gen, _, _, llm = _make_generator(
            tmp_path,
            fragments_content="   \n\n  ",
        )
        result = gen.generate("2026-06-27")
        assert result is None

    def test_overwindow_splits_and_merges(self, tmp_path: Path) -> None:
        """超窗碎片：按行分块分段概括、再合并（多次 LLM 调用）。"""
        from mcs_mem.diary import _DIARY_MAX_CHARS

        line = "一条用于撑大单日碎片总量的较长碎片内容测试超窗分段合并逻辑"
        n = (_DIARY_MAX_CHARS // len(line)) + 5
        long_md = "\n".join(f"{i % 24:02d}:{i % 60:02d} {line}{i}" for i in range(n))
        assert len(long_md) > _DIARY_MAX_CHARS

        gen, _, _, llm = _make_generator(
            tmp_path, fragments_content=long_md, llm_response="日记片段"
        )
        result = gen.generate("2026-06-27")
        assert result is not None
        # 超窗 → 多次 LLM 调用（分段各一次 + 合并一次），> 1
        assert len(llm.calls) > 1

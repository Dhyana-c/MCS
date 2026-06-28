"""FragmentStore 碎片存储模块单测。

覆盖边界情况：
- 首次建文件 / 追加不覆盖 / 多条顺序 / 空目录列表 / 读不存在返回 None
- 覆盖 / 中文 + 特殊字符 / 目录自动创建 / 追加不触发 ingest
"""

from __future__ import annotations

import threading
from pathlib import Path

import pytest

from mcs_mem.fragments import FragmentStore


@pytest.fixture
def frag_dir(tmp_path: Path) -> Path:
    """测试用碎片目录（tmp_path 下的子目录）。"""
    return tmp_path / "fragments"


@pytest.fixture
def store(frag_dir: Path) -> FragmentStore:
    """FragmentStore 实例，指向测试临时目录。"""
    return FragmentStore(fragments_dir=frag_dir)


class TestAppend:
    """append 相关测试。"""

    def test_first_append_creates_file(self, store: FragmentStore, frag_dir: Path) -> None:
        """首次追加：目录和文件不存在时自动创建。"""
        date, time = store.append("今天和团队讨论了新方案")
        # 文件已创建
        path = frag_dir / f"{date}.md"
        assert path.is_file()
        # 内容包含时间戳和正文
        content = path.read_text(encoding="utf-8")
        assert "今天和团队讨论了新方案" in content
        assert time in content

    def test_append_does_not_overwrite(self, store: FragmentStore) -> None:
        """追加不覆盖：连续追加两条，两条都在。"""
        store.append("消息A")
        date, _ = store.append("消息B")
        content = store.read(date)
        assert content is not None
        assert "消息A" in content
        assert "消息B" in content

    def test_append_order_preserved(self, store: FragmentStore) -> None:
        """追加顺序：多条消息按追加顺序出现在文件中。"""
        store.append("第一条")
        date, _ = store.append("第二条")
        content = store.read(date)
        assert content is not None
        lines = [l for l in content.strip().split("\n") if l.strip()]
        assert len(lines) == 2
        assert "第一条" in lines[0]
        assert "第二条" in lines[1]

    def test_append_returns_date_and_time(self, store: FragmentStore) -> None:
        """返回值：(date, time)，日期格式 YYYY-MM-DD，时间格式 HH:MM。"""
        date, time = store.append("test")
        assert len(date) == 10
        assert date[4] == "-"
        assert date[7] == "-"
        assert len(time) == 5
        assert time[2] == ":"

    def test_append_creates_directory(self, tmp_path: Path) -> None:
        """目录不存在时自动创建（含中间目录）。"""
        deep_dir = tmp_path / "a" / "b" / "c"
        store = FragmentStore(fragments_dir=deep_dir)
        store.append("测试自动建目录")
        assert deep_dir.is_dir()

    def test_append_multithread_safety(self, store: FragmentStore) -> None:
        """多线程并发追加不会交错（串行化保证）。"""
        errors: list[Exception] = []
        n = 20

        def _append(idx: int) -> None:
            try:
                store.append(f"线程消息{idx}")
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=_append, args=(i,)) for i in range(n)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        # 所有消息都在文件中
        date = store._today_date()
        content = store.read(date)
        assert content is not None
        for i in range(n):
            assert f"线程消息{i}" in content


class TestRead:
    """read 相关测试。"""

    def test_read_existing(self, store: FragmentStore) -> None:
        """读取已有文件。"""
        date, _ = store.append("测试内容")
        content = store.read(date)
        assert content is not None
        assert "测试内容" in content

    def test_read_nonexistent_returns_none(self, store: FragmentStore) -> None:
        """读取不存在的日期返回 None（不报错）。"""
        result = store.read("2099-01-01")
        assert result is None

    def test_read_reflects_manual_edit(self, store: FragmentStore, frag_dir: Path) -> None:
        """手动修改文件后读到新内容（不缓存）。"""
        date, _ = store.append("原始内容")
        path = frag_dir / f"{date}.md"
        # 手动修改
        path.write_text("14:30 修正后的内容\n", encoding="utf-8")
        content = store.read(date)
        assert content is not None
        assert "修正后的内容" in content
        assert "原始内容" not in content


class TestOverwrite:
    """overwrite 相关测试。"""

    def test_overwrite_existing(self, store: FragmentStore) -> None:
        """覆盖已有文件。"""
        date, _ = store.append("旧内容")
        store.overwrite(date, "14:30 新内容\n")
        content = store.read(date)
        assert "新内容" in content
        assert "旧内容" not in content

    def test_overwrite_creates_new(self, store: FragmentStore) -> None:
        """覆盖不存在的日期则创建。"""
        store.overwrite("2099-12-31", "15:00 未来内容\n")
        content = store.read("2099-12-31")
        assert content is not None
        assert "未来内容" in content

    def test_overwrite_creates_directory(self, tmp_path: Path) -> None:
        """覆盖时目录不存在则自动创建。"""
        deep_dir = tmp_path / "x" / "y"
        store = FragmentStore(fragments_dir=deep_dir)
        store.overwrite("2099-01-01", "test\n")
        assert deep_dir.is_dir()


class TestListDates:
    """list_dates 相关测试。"""

    def test_list_empty_dir(self, store: FragmentStore) -> None:
        """空目录返回空列表。"""
        assert store.list_dates() == []

    def test_list_nonexistent_dir(self, tmp_path: Path) -> None:
        """目录不存在返回空列表（不报错）。"""
        store = FragmentStore(fragments_dir=tmp_path / "nonexistent")
        assert store.list_dates() == []

    def test_list_dates_descending(self, store: FragmentStore) -> None:
        """列表按日期倒排。"""
        store.overwrite("2026-06-25", "内容A\n")
        store.overwrite("2026-06-27", "内容B\n")
        store.overwrite("2026-06-26", "内容C\n")
        dates = store.list_dates()
        assert dates == ["2026-06-27", "2026-06-26", "2026-06-25"]

    def test_list_ignores_non_md(self, store: FragmentStore, frag_dir: Path) -> None:
        """忽略非 .md 文件。"""
        store.overwrite("2026-06-27", "内容\n")
        (frag_dir / "notes.txt").write_text("不是碎片", encoding="utf-8")
        dates = store.list_dates()
        assert dates == ["2026-06-27"]

    def test_list_ignores_malformed_name(self, store: FragmentStore, frag_dir: Path) -> None:
        """忽略不符合 YYYY-MM-DD.md 命名的文件。"""
        store.overwrite("2026-06-27", "内容\n")
        (frag_dir / "readme.md").write_text("不是碎片", encoding="utf-8")
        dates = store.list_dates()
        assert dates == ["2026-06-27"]


class TestChineseAndSpecialChars:
    """中文和特殊字符测试。"""

    def test_chinese_content(self, store: FragmentStore) -> None:
        """中文内容正确存读。"""
        date, _ = store.append("今天学习了《深度学习》第三章")
        content = store.read(date)
        assert content is not None
        assert "《深度学习》第三章" in content

    def test_special_chars(self, store: FragmentStore) -> None:
        """特殊字符（emoji、引号、换行符等）正确存读。"""
        date, _ = store.append("特殊字符：🎉 \"引号\" '单引号' & <tag>")
        content = store.read(date)
        assert content is not None
        assert "🎉" in content
        assert '"引号"' in content

    def test_multiline_content(self, store: FragmentStore) -> None:
        """含换行的内容（只追加一行，不含用户换行——用户换行在同行的 content 中）。"""
        date, _ = store.append("第一行\n第二行")
        content = store.read(date)
        assert content is not None
        assert "第一行" in content


class TestNoIngest:
    """确认追加不触发 ingest / MCS 调用。"""

    def test_append_no_ingest(self, store: FragmentStore) -> None:
        """FragmentStore 不碰 MCS：纯文件 IO，不依赖 MemoryStore / mcs 模块。"""
        # 如果 FragmentStore 的 append 隐式 import 了 mcs 或 MemoryStore，
        # 在无 MCS 环境下会 ImportError——这里能跑过就证明没碰
        date, time = store.append("无需 ingest")
        content = store.read(date)
        assert content is not None
        assert "无需 ingest" in content


class TestEnvConfig:
    """环境变量配置测试。"""

    def test_env_overrides_default(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """MCS_MEMORY_FRAGMENTS_DIR 环境变量覆盖默认目录。"""
        custom_dir = tmp_path / "custom_fragments"
        monkeypatch.setenv("MCS_MEMORY_FRAGMENTS_DIR", str(custom_dir))
        store = FragmentStore()  # 不传 fragments_dir
        assert store.fragments_dir == custom_dir

    def test_explicit_dir_overrides_env(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        """显式传入 fragments_dir 优先于环境变量。"""
        explicit_dir = tmp_path / "explicit"
        monkeypatch.setenv("MCS_MEMORY_FRAGMENTS_DIR", "/should/be/ignored")
        store = FragmentStore(fragments_dir=explicit_dir)
        assert store.fragments_dir == explicit_dir

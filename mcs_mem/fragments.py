"""碎片捕获层——当天 Markdown 碎片文件的存储与读写。

每日一个 ``YYYY-MM-DD.md`` 文件，每条消息以 ``HH:MM 内容`` 格式追加。
碎片是保真原始层：只存 / 读 / 列表 / 覆盖，不解析、不入图、不调 LLM。

存储目录默认 ``~/.mcs_memory/fragments/``（``Path.home()`` 兼容 Windows），
可通过构造参数或环境变量 ``MCS_MEMORY_FRAGMENTS_DIR`` 配置。

追加串行化：同进程内用 threading.Lock 保证多线程追加不交错（捕获是纯文件 IO，
不经 MemoryStore 的 worker 线程——它根本不碰 MCS）。
"""

from __future__ import annotations

import os
import threading
from datetime import datetime
from pathlib import Path
from typing import Optional

__all__ = ["FragmentStore", "VersionMismatch"]


def _default_fragments_dir() -> Path:
    """默认碎片目录：``~/.mcs_memory/fragments/``，环境变量可覆盖。"""
    env = os.environ.get("MCS_MEMORY_FRAGMENTS_DIR")
    if env:
        return Path(env)
    return Path.home() / ".mcs_memory" / "fragments"


class VersionMismatch(Exception):
    """乐观锁冲突：PUT 的 ``expected_mtime`` 与文件当前 mtime 不符（期间被 ``/note`` 追加等改动）。"""


class FragmentStore:
    """当天 MD 碎片捕获层：按日期归档、实时追加、人工 / API 编辑、列表 / 读取。

    Args:
        fragments_dir: 碎片目录路径；None 取默认（env 或 ``~/.mcs_memory/fragments/``）。
    """

    def __init__(self, fragments_dir: Optional[Path] = None) -> None:
        self._dir = Path(fragments_dir) if fragments_dir else _default_fragments_dir()
        self._lock = threading.Lock()

    @property
    def fragments_dir(self) -> Path:
        """碎片目录路径（只读）。"""
        return self._dir

    def _ensure_dir(self) -> None:
        """目录不存在则自动创建（含中间目录）。"""
        self._dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _today_date() -> str:
        """当前日期字符串 ``YYYY-MM-DD``。"""
        return datetime.now().strftime("%Y-%m-%d")

    @staticmethod
    def _now_time() -> str:
        """当前时间字符串 ``HH:MM``。"""
        return datetime.now().strftime("%H:%M")

    def _path(self, date: str) -> Path:
        """指定日期的碎片文件路径。"""
        return self._dir / f"{date}.md"

    def append(self, content: str) -> tuple[str, str]:
        """追加一条消息到当天碎片文件。

        以 ``HH:MM 内容`` 格式追加到当天 MD 文件末尾。
        目录 / 文件不存在则自动创建。追加串行化（线程安全）。

        Args:
            content: 消息正文（不含时间前缀）。

        Returns:
            (date, time)：当天日期和追加时的时间戳。
        """
        date = self._today_date()
        time = self._now_time()
        line = f"{time} {content}\n"
        with self._lock:
            self._ensure_dir()
            path = self._path(date)
            # 追加模式：文件不存在则创建，存在则在末尾追加
            with open(path, "a", encoding="utf-8") as f:
                f.write(line)
        return date, time

    def read(self, date: str) -> Optional[str]:
        """读取指定日期的碎片全文。

        Args:
            date: 日期字符串 ``YYYY-MM-DD``。

        Returns:
            文件全文内容；不存在返回 None（不报错）。
        """
        path = self._path(date)
        if not path.is_file():
            return None
        return path.read_text(encoding="utf-8")

    def mtime(self, date: str) -> Optional[float]:
        """指定日期碎片文件的 mtime（修改时间戳）；不存在返回 None。供 PUT 乐观锁校验。"""
        path = self._path(date)
        if not path.is_file():
            return None
        return path.stat().st_mtime

    def overwrite(
        self, date: str, content: str, expected_mtime: Optional[float] = None
    ) -> None:
        """整文件覆盖指定日期的碎片（供 ``PUT`` API）。

        不存在则创建（自动建目录）。若 ``expected_mtime`` 给定且与文件当前 mtime 不符，
        抛 ``VersionMismatch``——乐观锁，防编辑器载入后、保存前被 ``/note`` 追加致覆盖丢行。

        Args:
            date: 日期字符串 ``YYYY-MM-DD``。
            content: 完整文件内容。
            expected_mtime: 调用方载入时的 mtime；给定则校验，不符抛 VersionMismatch。
        """
        with self._lock:
            self._ensure_dir()
            path = self._path(date)
            if expected_mtime is not None and path.is_file():
                if path.stat().st_mtime != expected_mtime:
                    raise VersionMismatch(date)
            path.write_text(content, encoding="utf-8")

    def list_dates(self) -> list[str]:
        """列出已有碎片文件的日期，按日期倒排。

        Returns:
            日期字符串列表（如 ``["2026-06-27", "2026-06-26"]``），
            仅含符合 ``YYYY-MM-DD.md`` 命名的文件。
        """
        if not self._dir.is_dir():
            return []
        dates: list[str] = []
        for p in self._dir.iterdir():
            if p.suffix == ".md" and len(p.stem) == 10 and p.stem[4] == "-" and p.stem[7] == "-":
                dates.append(p.stem)
        dates.sort(reverse=True)
        return dates

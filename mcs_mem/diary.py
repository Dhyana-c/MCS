"""日记生成——当天碎片概括成一篇人读的日记 Markdown。

输入：当天 MD 碎片（Slice 1 FragmentStore.read(date)）。
输出：一篇日记 Markdown，存独立目录（~/.mcs_memory/diaries/），不进图。
LLM：复用 mcs_agent 的 llm_call，独立的"概括"prompt。

日记可重生成（覆盖），无单日锁定。
"""

from __future__ import annotations

import logging
import os
import threading
from pathlib import Path
from typing import Any, Optional, Protocol

__all__ = ["DiaryStore", "DiaryGenerator"]

logger = logging.getLogger(__name__)

_DIARY_PROMPT = """\
你是日记撰写助手。今天是 {date}。根据以下 {date} 当天记忆碎片（按时间排列），写一篇连贯的第一人称日记叙述。

要求：
1. 仅基于碎片内容，不杜撰未提及的事（**包括天气**——碎片没提就不要写天气）
2. **日期 / 星期必须用给定的 {date}**（星期可由 {date} 推算）；MUST NOT 自行编造其他日期或猜测星期
3. 覆盖每条碎片的关键信息，不因"不重要"而整条略过
4. 按时间顺序组织，保持自然流畅
5. 用第一人称，语气自然
6. 输出纯 Markdown 文本

{date} 当天碎片：
{fragments}
"""

# 超窗阈值（字符代理——日记生成无 token 估算能力）：碎片超此长度按行分块分段概括再合并。
_DIARY_MAX_CHARS = 4000

_DIARY_MERGE_PROMPT = """\
以下是同一天碎片按时间段分段概括出的草稿（已各自成文）。请把它们合并成一篇连贯的第一人称日记，
保留每段关键信息、按时间顺序、不杜撰、不遗漏：

草稿：
{parts}
"""


def _default_diaries_dir() -> Path:
    """默认日记目录：``~/.mcs_memory/diaries/``，环境变量可覆盖。"""
    env = os.environ.get("MCS_MEMORY_DIARIES_DIR")
    if env:
        return Path(env)
    return Path.home() / ".mcs_memory" / "diaries"


class DiaryStore:
    """日记存储：按日期读写日记 Markdown 文件。

    Args:
        diaries_dir: 日记目录路径；None 取默认。
    """

    def __init__(self, diaries_dir: Optional[Path] = None) -> None:
        self._dir = Path(diaries_dir) if diaries_dir else _default_diaries_dir()
        self._lock = threading.Lock()

    @property
    def diaries_dir(self) -> Path:
        return self._dir

    def _ensure_dir(self) -> None:
        self._dir.mkdir(parents=True, exist_ok=True)

    def _path(self, date: str) -> Path:
        return self._dir / f"{date}.md"

    def write(self, date: str, content: str) -> None:
        """写入/覆盖指定日期的日记。"""
        with self._lock:
            self._ensure_dir()
            self._path(date).write_text(content, encoding="utf-8")

    def read(self, date: str) -> Optional[str]:
        """读取指定日期的日记；不存在返回 None。"""
        path = self._path(date)
        if not path.is_file():
            return None
        return path.read_text(encoding="utf-8")

    def list_dates(self) -> list[str]:
        """列出已有日记日期，按日期倒排。"""
        if not self._dir.is_dir():
            return []
        dates: list[str] = []
        for p in self._dir.iterdir():
            if p.suffix == ".md" and len(p.stem) == 10 and p.stem[4] == "-" and p.stem[7] == "-":
                dates.append(p.stem)
        dates.sort(reverse=True)
        return dates


class _LLMProto(Protocol):
    def chat(self, messages: list[dict], tools: list[dict]) -> Any: ...


class _FragmentStoreProto(Protocol):
    def read(self, date: str) -> Optional[str]: ...


class DiaryGenerator:
    """日记生成器：读碎片 → LLM 概括 → 写日记。

    Args:
        fragment_store: 碎片存储（Slice 1 FragmentStore）。
        diary_store: 日记存储。
        llm: agent 的 LLM 后端（需暴露 chat 方法）。
    """

    def __init__(
        self,
        fragment_store: Any,
        diary_store: DiaryStore,
        llm: Any,
    ) -> None:
        self._fragments = fragment_store
        self._diary = diary_store
        self._llm = llm

    def generate(self, date: str) -> Optional[str]:
        """生成指定日期的日记。

        碎片超窗（超 ``_DIARY_MAX_CHARS`` 字符）时按行分块分段概括、再合并成一篇；否则一次概括。
        无 token 估算能力，用字符数作超窗代理（产物侧纯摘要分段，不入图、不与整合语义分段重复）。

        Returns:
            日记文本；当天无碎片返回 None。
        """
        md_text = self._fragments.read(date)
        if not md_text or not md_text.strip():
            return None

        if len(md_text) <= _DIARY_MAX_CHARS:
            diary_text = self._summarize(md_text, date)
        else:
            diary_text = self._summarize_long(md_text, date)

        if not diary_text.strip():
            return None

        self._diary.write(date, diary_text)
        return diary_text

    def _call_llm(self, user_prompt: str, system: str = "你是日记撰写助手。") -> str:
        """调 LLM，返回文本（失败抛——由调用方 catch）。"""
        messages = [
            {"role": "system", "content": system},
            {"role": "user", "content": user_prompt},
        ]
        response = self._llm.chat(messages, [])
        if hasattr(response, "content"):
            return response.content or ""
        if isinstance(response, dict):
            return response.get("content", "")
        return str(response)

    def _summarize(self, fragments_text: str, date: str) -> str:
        """一次概括（碎片 ≤ 窗口）。date 传入 prompt 防 LLM 杜撰日期 / 星期 / 天气。"""
        return self._call_llm(_DIARY_PROMPT.format(fragments=fragments_text, date=date))

    def _summarize_long(self, md_text: str, date: str) -> str:
        """超窗：按行分块分段概括 → 再合并成一篇连贯日记。date 传入防 LLM 杜撰日期。"""
        lines = md_text.splitlines()
        chunks: list[str] = []
        cur: list[str] = []
        cur_len = 0
        for line in lines:
            if cur and cur_len + len(line) > _DIARY_MAX_CHARS:
                chunks.append("\n".join(cur))
                cur = [line]
                cur_len = len(line)
            else:
                cur.append(line)
                cur_len += len(line) + 1  # +1 换行
        if cur:
            chunks.append("\n".join(cur))

        parts = [self._summarize(c, date) for c in chunks]
        try:
            return self._call_llm(
                _DIARY_MERGE_PROMPT.format(parts="\n\n---\n\n".join(parts)),
                system="你是日记撰写助手，负责把分段草稿合并成一篇连贯日记。",
            )
        except Exception:
            logger.error("日记合并 LLM 调用失败", exc_info=True)
            raise

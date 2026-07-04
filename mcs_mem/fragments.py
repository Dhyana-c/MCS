"""碎片捕获层——结构化逐条碎片（JSONL per day）+ 三态状态机。

每日一个 ``YYYY-MM-DD.jsonl`` 文件，每行一个碎片 JSON 对象
``{id, date, time, content, status, event_id, created_at}``。碎片是**有状态的一等对象**：
``status`` ∈ ``pending``（默认，可改 / 删 / 确认）/ ``confirming``（确认进行中，只读）/
``confirmed``（已入图，只读、挂 ``event_id``）。

本层是**纯文件 IO 旁路、不触碰 MCS**：状态原语（``begin_confirm`` / ``confirm_mark`` /
``abort_confirm``）只标文件、不调 ``ingest``——确认即入图的协调（串原语 + ingest）归
``agent-consolidation`` 层（``Consolidator.confirm_one``）。

存储目录默认 ``~/.mcs_memory/fragments/``（``Path.home()`` 兼容 Windows），
可通过构造参数或环境变量 ``MCS_MEMORY_FRAGMENTS_DIR`` 配置。

并发：同进程内用 ``threading.Lock`` 串行化碎片追加 / 改 / 删 / 状态原语（捕获纯文件 IO，
不经 MemoryStore 的 worker 线程——它根本不碰 MCS）。``begin_confirm`` 的 ``pending →
confirming`` CAS 在锁内原子完成，保证并发确认同一条不重复入图。

初始化时做两件**幂等**事：① 把遗留的 ``.md`` 碎片（旧 ``HH:MM 内容`` 行格式）迁移为
``.jsonl``（``.md`` 重命名为 ``.md.migrated`` 备份）；② 把崩溃残留的 ``confirming`` 碎片
回退为 ``pending``（``begin_confirm`` 后、``confirm_mark`` 前进程挂掉的悬空态）。
"""

from __future__ import annotations

import json
import logging
import os
import re
import threading
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Optional

__all__ = [
    "Fragment",
    "FragmentStore",
    "FragmentNotFound",
    "FragmentStateError",
    "parse_fragments",
]

logger = logging.getLogger(__name__)

_STATUSES = ("pending", "confirming", "confirmed")

# 旧 MD 行格式 ``HH:MM 内容``（仅迁移用途）。
_HHMM_RE = re.compile(r"^(\d{2}:\d{2})\s+(.+)$")

# 合法日期主干（frag_id 日期前缀校验，防 URL 入参路径穿越逃出 fragments_dir）。
_DATE_STEM_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def parse_fragments(md_text: str, date: str) -> list[tuple[str, str]]:
    """逐行解析碎片 MD 为 (iso_timestamp, content) 序列（**仅 MD→JSONL 迁移用途**）。

    行格式 ``HH:MM 内容``，timestamp 由 date + HH:MM 组成 ISO 8601。
    无法解析的行跳过 + WARNING；不调 LLM、不做语义分段。

    Args:
        md_text: 碎片文件全文。
        date: 文件名日期 ``YYYY-MM-DD``。

    Returns:
        [(iso_timestamp, content), ...] 列表。
    """
    results: list[tuple[str, str]] = []
    for line in md_text.splitlines():
        line = line.strip()
        if not line:
            continue
        m = _HHMM_RE.match(line)
        if m:
            hhmm = m.group(1)
            content = m.group(2).strip()
            if not content:
                continue
            iso_ts = f"{date}T{hhmm}:00"
            results.append((iso_ts, content))
        else:
            logger.warning("跳过无法解析的行: %r", line)
    return results


class FragmentNotFound(Exception):
    """指定 id 的碎片不存在。"""


class FragmentStateError(Exception):
    """非法状态转移 / 对非 pending 碎片做改 / 删（confirming / confirmed 只读）。"""


@dataclass
class Fragment:
    """一条结构化碎片。

    Attributes:
        id: 全碎片空间唯一标识，``{date}T{HH:MM:SS}``（同秒冲突追加 ``-N``）。
        date: ``YYYY-MM-DD``。
        time: ``HH:MM``（展示用）。
        content: 正文。
        status: ``pending`` / ``confirming`` / ``confirmed``。
        event_id: 确认入图后关联的事件 id；``pending`` / ``confirming`` 时为 None。
        created_at: 创建时刻 ISO 8601。
    """

    id: str
    date: str
    time: str
    content: str
    status: str = "pending"
    event_id: Optional[str] = None
    created_at: str = ""

    def to_dict(self) -> dict:
        return asdict(self)

    def to_json_line(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)

    @classmethod
    def from_dict(cls, d: dict) -> "Fragment":
        return cls(
            id=d["id"],
            date=d["date"],
            time=d["time"],
            content=d["content"],
            status=d.get("status", "pending"),
            event_id=d.get("event_id"),
            created_at=d.get("created_at", ""),
        )


def _default_fragments_dir() -> Path:
    """默认碎片目录：``~/.mcs_memory/fragments/``，环境变量可覆盖。"""
    env = os.environ.get("MCS_MEMORY_FRAGMENTS_DIR")
    if env:
        return Path(env)
    return Path.home() / ".mcs_memory" / "fragments"


def _is_date_stem(stem: str) -> bool:
    """文件名主干是否形如 ``YYYY-MM-DD``。"""
    return len(stem) == 10 and stem[4] == "-" and stem[7] == "-"


class FragmentStore:
    """结构化碎片捕获层：JSONL 逐条存储、三态状态机、逐条 CRUD。

    Args:
        fragments_dir: 碎片目录路径；None 取默认（env 或 ``~/.mcs_memory/fragments/``）。
    """

    def __init__(self, fragments_dir: Optional[Path] = None) -> None:
        self._dir = Path(fragments_dir) if fragments_dir else _default_fragments_dir()
        self._lock = threading.Lock()
        # 初始化幂等维护（构造期单线程，直接用 nolock 帮助函数）。
        self._migrate_md_to_jsonl()
        self._cleanup_confirming()

    @property
    def fragments_dir(self) -> Path:
        """碎片目录路径（只读）。"""
        return self._dir

    # --- 路径 / 时间 ---

    def _ensure_dir(self) -> None:
        """目录不存在则自动创建（含中间目录）。"""
        self._dir.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _today_date() -> str:
        return datetime.now().strftime("%Y-%m-%d")

    @staticmethod
    def _now_time() -> str:
        return datetime.now().strftime("%H:%M")

    @staticmethod
    def _now_hms() -> str:
        return datetime.now().strftime("%H:%M:%S")

    def _path(self, date: str) -> Path:
        """指定日期的碎片 JSONL 文件路径。"""
        return self._dir / f"{date}.jsonl"

    @staticmethod
    def _date_of(frag_id: str) -> str:
        """从碎片 id 还原日期前缀（``{date}T...``）。"""
        return frag_id.split("T", 1)[0]

    @staticmethod
    def _validated_date(frag_id: str) -> str:
        """从 frag_id 还原并校验日期前缀；非法（含 ``..`` / 分隔符等路径穿越）抛 ValueError。

        ``_date_of`` 仅切 ``T`` 前缀、不校验。URL 入参的 frag_id MUST 经此校验后再拼路径，
        否则 ``../x`` 会逃出 ``fragments_dir``（update / delete / 确认原语均经此）。
        """
        date = FragmentStore._date_of(frag_id)
        if not _DATE_STEM_RE.match(date):
            raise ValueError(f"非法 frag_id: {frag_id!r}")
        return date

    @staticmethod
    def _unique_id(base: str, existing: set[str]) -> str:
        """同 base 已存在则追加 ``-2`` / ``-3`` …，保证当天文件内唯一。"""
        if base not in existing:
            return base
        n = 2
        while f"{base}-{n}" in existing:
            n += 1
        return f"{base}-{n}"

    # --- nolock 文件读写帮助函数（调用方须已持锁，或在构造期单线程） ---

    def _read_all_nolock(self, date: str) -> list[Fragment]:
        path = self._path(date)
        if not path.is_file():
            return []
        frags: list[Fragment] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                frags.append(Fragment.from_dict(json.loads(line)))
            except (json.JSONDecodeError, KeyError, TypeError):
                logger.warning("跳过无法解析的碎片行: %r", line)
        frags.sort(key=lambda f: (f.time, f.id))
        return frags

    def _write_all_nolock(self, date: str, frags: list[Fragment]) -> None:
        self._ensure_dir()
        path = self._path(date)
        body = "".join(f.to_json_line() + "\n" for f in frags)
        path.write_text(body, encoding="utf-8")

    # --- 写入 / 读取 ---

    def create(self, content: str) -> tuple[str, str, str]:
        """创建一条 ``pending`` 碎片追加到当天 JSONL。

        Args:
            content: 碎片正文（不含时间前缀）。

        Returns:
            ``(id, date, time)``。
        """
        date = self._today_date()
        time = self._now_time()
        hms = self._now_hms()
        with self._lock:
            existing = {f.id for f in self._read_all_nolock(date)}
            frag_id = self._unique_id(f"{date}T{hms}", existing)
            frag = Fragment(
                id=frag_id,
                date=date,
                time=time,
                content=content,
                status="pending",
                event_id=None,
                created_at=datetime.now().isoformat(timespec="seconds"),
            )
            self._ensure_dir()
            with open(self._path(date), "a", encoding="utf-8") as f:
                f.write(frag.to_json_line() + "\n")
        return frag_id, date, time

    def read_all(self, date: str) -> list[Fragment]:
        """返回指定日期全部碎片（各态混列，按 ``time`` 排序）。不存在返回空列表。"""
        with self._lock:
            return self._read_all_nolock(date)

    def get(self, frag_id: str) -> Optional[Fragment]:
        """按 id 取碎片；不存在返回 None。"""
        date = self._validated_date(frag_id)
        with self._lock:
            for f in self._read_all_nolock(date):
                if f.id == frag_id:
                    return f
        return None

    def find(self, date: str, frag_id: str) -> Optional[Fragment]:
        """在指定日期内按 id 取碎片；不存在返回 None。"""
        with self._lock:
            for f in self._read_all_nolock(date):
                if f.id == frag_id:
                    return f
        return None

    def update(self, frag_id: str, content: str) -> Fragment:
        """改碎片 ``content``，**仅 pending**。

        Raises:
            FragmentNotFound: id 不存在。
            FragmentStateError: 碎片非 pending（confirming / confirmed 只读）。
        """
        date = self._validated_date(frag_id)
        with self._lock:
            frags = self._read_all_nolock(date)
            for f in frags:
                if f.id == frag_id:
                    if f.status != "pending":
                        raise FragmentStateError(
                            f"碎片 {frag_id} 状态为 {f.status}，仅 pending 可编辑"
                        )
                    f.content = content
                    self._write_all_nolock(date, frags)
                    return f
        raise FragmentNotFound(frag_id)

    def delete(self, frag_id: str) -> None:
        """删碎片，**仅 pending**。

        Raises:
            FragmentNotFound: id 不存在。
            FragmentStateError: 碎片非 pending（confirming / confirmed 只读）。
        """
        date = self._validated_date(frag_id)
        with self._lock:
            frags = self._read_all_nolock(date)
            for i, f in enumerate(frags):
                if f.id == frag_id:
                    if f.status != "pending":
                        raise FragmentStateError(
                            f"碎片 {frag_id} 状态为 {f.status}，仅 pending 可删除"
                        )
                    del frags[i]
                    self._write_all_nolock(date, frags)
                    return
        raise FragmentNotFound(frag_id)

    # --- 三态状态原语（纯文件、内锁原子，不调 ingest / MCS） ---

    def begin_confirm(self, frag_id: str) -> bool:
        """原子 CAS ``pending → confirming``。

        Returns:
            True = 抢占成功（曾是 pending、现置 confirming）；
            False = 抢占失败（碎片不存在 / 已 confirming / 已 confirmed）。
        """
        date = self._validated_date(frag_id)
        with self._lock:
            frags = self._read_all_nolock(date)
            for f in frags:
                if f.id == frag_id:
                    if f.status != "pending":
                        return False
                    f.status = "confirming"
                    self._write_all_nolock(date, frags)
                    return True
            return False

    def attach_event(self, frag_id: str, event_id: str) -> None:
        """``confirming`` 态立即持久化 ``event_id``（不切状态）——重复入图自愈锚点。

        ``ingest_structured`` 成功后、``confirm_mark`` 前调用，把"事件已建"信号尽快落盘。
        崩溃恢复时 ``_cleanup_confirming`` 据 ``event_id`` 有无决定收敛 ``confirmed``（已建、
        不重 ingest）或回退 ``pending``（未建、可重试）。

        Raises:
            FragmentNotFound: id 不存在。
            FragmentStateError: 碎片非 confirming。
        """
        date = self._validated_date(frag_id)
        with self._lock:
            frags = self._read_all_nolock(date)
            for f in frags:
                if f.id == frag_id:
                    if f.status != "confirming":
                        raise FragmentStateError(
                            f"碎片 {frag_id} 状态为 {f.status}，attach_event 仅作用于 confirming"
                        )
                    f.event_id = event_id
                    self._write_all_nolock(date, frags)
                    return
            raise FragmentNotFound(frag_id)

    def confirm_mark(self, frag_id: str, event_id: str) -> None:
        """落定 ``confirming → confirmed`` 并写入 ``event_id``。

        Raises:
            FragmentNotFound: id 不存在。
            FragmentStateError: 碎片非 confirming（协调器应在 begin_confirm 成功后调用）。
        """
        date = self._validated_date(frag_id)
        with self._lock:
            frags = self._read_all_nolock(date)
            for f in frags:
                if f.id == frag_id:
                    if f.status != "confirming":
                        raise FragmentStateError(
                            f"碎片 {frag_id} 状态为 {f.status}，confirm_mark 仅作用于 confirming"
                        )
                    f.status = "confirmed"
                    f.event_id = event_id
                    self._write_all_nolock(date, frags)
                    return
        raise FragmentNotFound(frag_id)

    def abort_confirm(self, frag_id: str) -> None:
        """回退 ``confirming → pending``（清空 ``event_id`` 占位，供 ingest 失败重试）。

        Raises:
            FragmentNotFound: id 不存在。
            FragmentStateError: 碎片非 confirming。
        """
        date = self._validated_date(frag_id)
        with self._lock:
            frags = self._read_all_nolock(date)
            for f in frags:
                if f.id == frag_id:
                    if f.status != "confirming":
                        raise FragmentStateError(
                            f"碎片 {frag_id} 状态为 {f.status}，abort_confirm 仅作用于 confirming"
                        )
                    f.status = "pending"
                    f.event_id = None
                    self._write_all_nolock(date, frags)
                    return
        raise FragmentNotFound(frag_id)

    # --- 列表 ---

    def list_dates(self) -> list[str]:
        """列出已有碎片 JSONL 文件的日期，按日期倒排。"""
        if not self._dir.is_dir():
            return []
        dates: list[str] = []
        for p in self._dir.iterdir():
            if p.suffix == ".jsonl" and _is_date_stem(p.stem):
                dates.append(p.stem)
        dates.sort(reverse=True)
        return dates

    # --- 初始化幂等维护 ---

    def _migrate_md_to_jsonl(self) -> None:
        """把遗留 ``.md`` 碎片迁移为 ``.jsonl``（幂等：已有同日 ``.jsonl`` 则跳过）。

        解析旧 ``HH:MM 内容`` 行为 ``pending`` 碎片写 JSONL；原 ``.md`` 重命名为
        ``.md.migrated`` 备份（保留、不丢数据）。
        """
        if not self._dir.is_dir():
            return
        for p in sorted(self._dir.iterdir()):
            if p.suffix != ".md" or not _is_date_stem(p.stem):
                continue
            date = p.stem
            if self._path(date).exists():
                continue  # 已有 JSONL，幂等跳过
            try:
                md_text = p.read_text(encoding="utf-8")
            except OSError:
                logger.error("读取待迁移碎片失败: %s", p, exc_info=True)
                continue
            existing: set[str] = set()
            frags: list[Fragment] = []
            for iso_ts, content in parse_fragments(md_text, date):
                hhmm = iso_ts[11:16]
                frag_id = self._unique_id(iso_ts, existing)
                existing.add(frag_id)
                frags.append(
                    Fragment(
                        id=frag_id,
                        date=date,
                        time=hhmm,
                        content=content,
                        status="pending",
                        event_id=None,
                        created_at=iso_ts,
                    )
                )
            self._write_all_nolock(date, frags)
            p.rename(p.parent / (p.name + ".migrated"))
            logger.info("迁移碎片 %s.md → %s.jsonl（%d 条）", date, date, len(frags))

    def _cleanup_confirming(self) -> None:
        """启动清理：崩溃残留的 ``confirming`` 碎片据 ``event_id`` 收敛。

        - 有 ``event_id``（``ingest_structured`` 已成功、仅未 ``confirm_mark``）→ 收敛 ``confirmed``
          （事件已建，不重 ingest、防重复入图）。
        - 无 ``event_id``（``begin_confirm`` 后、ingest 前崩）→ 回退 ``pending``（可重试）。
        """
        for date in self.list_dates():
            frags = self._read_all_nolock(date)
            changed = False
            for f in frags:
                if f.status == "confirming":
                    if f.event_id:
                        f.status = "confirmed"
                    else:
                        f.status = "pending"
                        f.event_id = None
                    changed = True
            if changed:
                self._write_all_nolock(date, frags)
                logger.info("启动清理：%s 的残留 confirming 碎片已收敛", date)

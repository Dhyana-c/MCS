"""整合管线——确认指定日期剩余 ``pending`` 碎片入图（确认即 ingest）。

核心流程：读当天 ``pending`` 碎片（FragmentStore）→ 逐条 ``confirm_one`` 确认入图
（``begin_confirm`` CAS → ``ingest_structured`` → ``confirm_mark``，失败 ``abort_confirm``
回退）。一碎片一事件、时间忠实。

**无自动去噪**：过滤交回用户——用户删不要的 ``pending``，幸存的由 scheduler 兜底 /
手动确认入图。**无单日锁定**：当天后续新记的 ``pending`` 可再次整合（``consolidate`` 幂等
可重入，已 ``confirming`` / ``confirmed`` 自然跳过）。

两层互斥：``Consolidator._mutex`` 防同日并发整合；per-碎片 ``begin_confirm`` CAS 防
确认 vs 确认 / 确认 vs 整合并发重复入图（``ingest`` 不幂等）。

``ConsolidationTracker`` 降级为**观测**（本地 JSON，记每日期最后整合结果
``{date, last_run, confirmed, failed}``，不再因 ``done`` 拒重入）。
"""

from __future__ import annotations

import json
import logging
import re
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, Protocol

from mcs_mem.fragments import FragmentNotFound

__all__ = [
    "ConsolidationStatus",
    "ConsolidationTracker",
    "Consolidator",
]

logger = logging.getLogger(__name__)

_HMS_RE = re.compile(r"^\d{2}:\d{2}:\d{2}$")


def _fragment_timestamp(frag: Any) -> str:
    """碎片入图事件时间：优先取 id 中的秒级时间（``{date}T{HH:MM:SS}[-N]``）。

    ``frag.time`` 只有分钟精度——同一分钟多条碎片会在 recall 时间倒排里失去真实
    次序（次级键退化为随机 uuid）。id 里带秒，直接复用；形态异常（如老数据）退回
    ``time`` 补 ``:00`` 的旧口径。
    """
    tail = frag.id.split("T", 1)[1] if "T" in frag.id else ""
    hms = tail.split("-", 1)[0]
    if _HMS_RE.match(hms):
        return f"{frag.date}T{hms}"
    return f"{frag.date}T{frag.time}:00"


# --- 状态观测 ---

class ConsolidationStatus:
    """单日最后整合观测（不再是锁定状态）。"""

    def __init__(
        self,
        date: str,
        last_run: str = "",
        confirmed: int = 0,
        failed: int = 0,
    ) -> None:
        self.date = date
        self.last_run = last_run
        self.confirmed = confirmed
        self.failed = failed

    def to_dict(self) -> dict:
        return {
            "date": self.date,
            "last_run": self.last_run,
            "confirmed": self.confirmed,
            "failed": self.failed,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ConsolidationStatus":
        return cls(
            date=d.get("date", ""),
            last_run=d.get("last_run", ""),
            confirmed=d.get("confirmed", 0),
            failed=d.get("failed", 0),
        )


class ConsolidationTracker:
    """整合观测追踪（本地 JSON）——记录每日期最后整合结果，**不锁定**。

    与旧版不同：不再有 ``done`` / ``running`` 锁定拒重入；仅供前端 / 日志观测。
    并发整合的互斥由 ``Consolidator._mutex`` 负责（不在本类）。
    """

    def __init__(self, path: Optional[Path] = None) -> None:
        if path is None:
            base = Path.home() / ".mcs_memory"
            base.mkdir(parents=True, exist_ok=True)
            path = base / "consolidation_status.json"
        self._path = path
        self._lock = threading.Lock()
        self._data: dict[str, dict] = self._load()

    def _load(self) -> dict[str, dict]:
        if self._path.is_file():
            try:
                return json.loads(self._path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError):
                logger.warning("整合状态文件损坏，重新初始化")
        return {}

    def _save(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(
                json.dumps(self._data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError:
            logger.error("整合状态持久化失败", exc_info=True)

    def get(self, date: str) -> ConsolidationStatus:
        """获取某日最后整合观测；无记录返回默认（confirmed=0, failed=0）。"""
        with self._lock:
            d = self._data.get(date)
            if d is None:
                return ConsolidationStatus(date=date)
            return ConsolidationStatus.from_dict(d)

    def record(self, date: str, confirmed: int, failed: int) -> None:
        """记录某日最后整合结果（观测，不锁定）。"""
        with self._lock:
            self._data[date] = {
                "date": date,
                "last_run": datetime.now().isoformat(timespec="seconds"),
                "confirmed": confirmed,
                "failed": failed,
            }
            self._save()

    def get_all(self) -> list[ConsolidationStatus]:
        """获取所有已知日期的观测。"""
        with self._lock:
            return [ConsolidationStatus.from_dict(d) for d in self._data.values()]


# --- 协议（避免直接依赖具体类） ---


class _MemoryStoreProto(Protocol):
    def ingest_structured(self, content: str, timestamp: str) -> str: ...


class _FragmentStoreProto(Protocol):
    """碎片存储依赖面（Consolidator 串联的三态原语 + 读取）。"""

    def begin_confirm(self, frag_id: str) -> bool: ...

    def get(self, frag_id: str) -> Any: ...

    def read_all(self, date: str) -> list[Any]: ...

    def attach_event(self, frag_id: str, event_id: str) -> None: ...

    def confirm_mark(self, frag_id: str, event_id: str) -> None: ...

    def abort_confirm(self, frag_id: str) -> None: ...


# --- 整合主流程 ---


class Consolidator:
    """整合管线：确认指定日期剩余 ``pending`` 碎片入图（确认即 ingest）。

    Args:
        fragment_store: 碎片存储（``FragmentStore``，提供三态原语 + ``read_all``）。
        memory: 记忆底座（需暴露 ``ingest_structured``）。
        tracker: 整合观测追踪。
    """

    def __init__(
        self,
        fragment_store: _FragmentStoreProto,
        memory: _MemoryStoreProto,
        tracker: ConsolidationTracker,
    ) -> None:
        self._fragments = fragment_store
        self._memory = memory
        self._tracker = tracker
        self._mutex = threading.Lock()

    @property
    def tracker(self) -> ConsolidationTracker:
        """整合观测追踪（只读访问，供路由层 / 测试）。"""
        return self._tracker

    def confirm_one(self, frag_id: str) -> dict:
        """确认单条碎片入图：串联碎片层状态原语与 ``ingest``。

        流程：``begin_confirm`` CAS 抢占 → ``ingest_structured`` → ``attach_event``（立即持久化
        event_id，自愈锚点）→ ``confirm_mark``。``ingest`` 失败则 ``abort_confirm`` 回退 ``pending``
        并 re-raise（可重试）；``attach_event`` 后失败则保留 ``confirming+event_id`` 待重启收敛
        （不清锚点、防重复入图）。碎片非 ``pending`` → 不 ingest、幂等返回 ``already``。

        重复入图防御（最佳努力）：``ingest`` 非幂等 + event_id 事后才返回，理论窗口
        [ingest 成功, ``attach_event`` 落盘] 内崩溃仍会重复；此流程把窗口压到一次本地写、
        并据已落 event_id 自愈，崩溃后不再重复。

        Returns:
            ``{"ok": True, "id", "status", "event_id"}``；幂等返回时附 ``"already": True``。

        Raises:
            FragmentNotFound: id 不存在。
            Exception: ``ingest_structured`` 抛错（已 abort_confirm 回退 pending）。
        """
        # CAS 抢占 pending → confirming；失败 = 不存在 / 已 confirming / 已 confirmed。
        if not self._fragments.begin_confirm(frag_id):
            cur = self._fragments.get(frag_id)
            if cur is None:
                raise FragmentNotFound(frag_id)
            return {
                "ok": True,
                "id": frag_id,
                "status": cur.status,
                "event_id": cur.event_id,
                "already": True,
            }

        # CAS 成功后**重取**权威快照：此刻碎片为 confirming、content/time 已冻结（update /
        # delete 要求 pending 会被拒），避免「初次读取 → begin_confirm」窗口内的并发编辑
        # 导致 ingest 旧内容。
        frag = self._fragments.get(frag_id)
        if frag is None:  # 理论不达：confirming 不可删
            raise FragmentNotFound(frag_id)

        try:
            # 事件时间 = 碎片时间（优先取 id 中的秒级时间，退回分钟精度补 :00）。
            ts = _fragment_timestamp(frag)
            event_id = self._memory.ingest_structured(frag.content, ts)
        except Exception:
            # ingest 失败：事件未建（write_pipeline 失败时回滚 ⓪ 节点），安全回退
            # pending 可重试。
            self._fragments.abort_confirm(frag_id)
            logger.error("confirm_one ingest 失败: id=%s", frag_id, exc_info=True)
            raise

        # —— 此后事件已建，MUST NOT abort（abort → pending → 重 ingest → 重复入图）——
        try:
            # ingest 成功后**立即**把 event_id 持久化到 confirming 态（自愈锚点）——缩短
            # "事件已建但未落定"窗口；崩溃恢复据 event_id 收敛 confirmed、防重复入图。
            self._fragments.attach_event(frag_id, event_id)
        except Exception:
            # 锚点写失败（本地 IO 异常）：事件已建，不回退；继续尝试 confirm_mark——
            # 它单次写同时落 status+event_id，成功即完全一致。
            logger.error(
                "confirm_one attach_event 失败: id=%s（事件已建，继续尝试 confirm_mark）",
                frag_id,
                exc_info=True,
            )
        try:
            self._fragments.confirm_mark(frag_id, event_id)
        except Exception:
            # 锚点已落 → 保留 confirming+event_id 供重启 _cleanup_confirming 收敛 confirmed；
            # 锚点未落（attach 也失败）→ 重启会回退 pending、重试可能重复入图，此处
            # 只能大声报错（本地文件连续写失败，无更优解）。
            logger.error(
                "confirm_one confirm_mark 失败: id=%s（事件已建 event_id=%s，待自愈收敛）",
                frag_id,
                event_id,
                exc_info=True,
            )
            raise
        return {
            "ok": True,
            "id": frag_id,
            "status": "confirmed",
            "event_id": event_id,
        }

    def consolidate(self, date: str) -> dict:
        """确认指定日期剩余 ``pending`` 碎片入图。

        互斥锁防同日并发整合（运行中再触发返回"正在整合中"）。幂等：已 confirming /
        confirmed 自然跳过；当天后续新 ``pending`` 可再次整合（无单日锁定）。

        Returns:
            ``{"ok", "date", "confirmed", "skipped", "failed", "warning"?}``。
        """
        if not self._mutex.acquire(blocking=False):
            return {
                "ok": False,
                "date": date,
                "confirmed": 0,
                "skipped": 0,
                "failed": 0,
                "warning": "整合正在进行中",
            }
        try:
            return self._do_consolidate(date)
        finally:
            self._mutex.release()

    def _do_consolidate(self, date: str) -> dict:
        """实际整合逻辑（已持互斥锁）。"""
        frags = self._fragments.read_all(date)
        pending_ids = [f.id for f in frags if f.status == "pending"]
        # 非 pending（confirming / confirmed）自然跳过 = 幂等。
        skipped = len(frags) - len(pending_ids)
        confirmed = 0
        failed = 0

        for frag_id in pending_ids:
            try:
                res = self.confirm_one(frag_id)
                if res.get("already"):
                    skipped += 1  # 被单条确认并发抢占（confirming / confirmed）
                elif res.get("status") == "confirmed":
                    confirmed += 1
                else:
                    skipped += 1  # 理论不达：confirm_one 要么 confirmed 要么 already 要么 raise
            except FragmentNotFound:
                skipped += 1  # 竞态删除：忽略
            except Exception:
                failed += 1  # ingest 失败（confirm_one 已 abort 回退 pending），续跑不中断

        self._tracker.record(date, confirmed=confirmed, failed=failed)
        return {
            "ok": True,
            "date": date,
            "confirmed": confirmed,
            "skipped": skipped,
            "failed": failed,
        }

"""整合管线——碎片去噪后逐条 ingest 入图。

核心流程：读当天 MD（FragmentStore）→ 逐行解析 → 去噪（Consolidator 应用层前置过滤）
→ 逐条 ingest_structured 入图（一碎片一事件、时间忠实）。

去噪在 Consolidator 内部、ingest 调用之前执行——不能落 WRITE_PREPROCESS 插件位
（该插件契约纯变换、MUST NOT skip，丢不掉输入；见 plugin-protocol spec）。

整合状态由 ConsolidationTracker 追踪（本地 JSON，单日锁定，done 后不重整）。
"""

from __future__ import annotations

import json
import logging
import re
import threading
from datetime import datetime
from pathlib import Path
from typing import Any, Optional, Protocol

from mcs_mem.prompts.denoise import DENOISE_PROMPT

__all__ = [
    "parse_fragments",
    "ConsolidationStatus",
    "ConsolidationTracker",
    "Consolidator",
]

logger = logging.getLogger(__name__)

# --- 解析 ---

_HHMM_RE = re.compile(r"^(\d{2}:\d{2})\s+(.+)$")


def parse_fragments(md_text: str, date: str) -> list[tuple[str, str]]:
    """逐行解析碎片 MD 为 (iso_timestamp, content) 序列。

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


# --- 状态追踪 ---

class ConsolidationStatus:
    """单日整合状态。"""

    def __init__(
        self,
        date: str,
        status: str = "pending",
        events: int = 0,
        consolidated_at: str = "",
        failures: int = 0,
        succeeded_ts: Optional[list[str]] = None,
    ) -> None:
        self.date = date
        self.status = status  # pending / running / done / failed
        self.events = events
        self.consolidated_at = consolidated_at
        # 部分失败可见化 + 重试幂等去重（见 _do_consolidate）：
        #   failures —— 单条 ingest 失败条数（失败计数，让 failed 状态可见、不被掩盖为 done）；
        #   succeeded_ts —— 已成功入图碎片的 timestamp 集合。failed 重跑时跳过这些碎片，
        #                   保证幂等、不重复入图（ingest 不幂等）。done 时清空（全成功、无需保留）。
        self.failures = failures
        self.succeeded_ts: list[str] = list(succeeded_ts) if succeeded_ts else []

    def to_dict(self) -> dict:
        return {
            "date": self.date,
            "status": self.status,
            "events": self.events,
            "consolidated_at": self.consolidated_at,
            "failures": self.failures,
            "succeeded_ts": self.succeeded_ts,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "ConsolidationStatus":
        return cls(
            date=d.get("date", ""),
            status=d.get("status", "pending"),
            events=d.get("events", 0),
            consolidated_at=d.get("consolidated_at", ""),
            failures=d.get("failures", 0),
            succeeded_ts=d.get("succeeded_ts", []),
        )


class ConsolidationTracker:
    """整合状态追踪（本地 JSON），单日锁定。

    某日 ``done`` 后锁定：再触发返回 ``already``，不重跑，无 force。
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
        """从磁盘加载持久化状态；文件不存在返回空。"""
        if self._path.is_file():
            try:
                text = self._path.read_text(encoding="utf-8")
                return json.loads(text)
            except (json.JSONDecodeError, OSError):
                logger.warning("整合状态文件损坏，重新初始化")
        return {}

    def _save(self) -> None:
        """持久化到磁盘。"""
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            self._path.write_text(
                json.dumps(self._data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        except OSError:
            logger.error("整合状态持久化失败", exc_info=True)

    def get(self, date: str) -> ConsolidationStatus:
        """获取某日状态；不存在返回 pending。"""
        with self._lock:
            d = self._data.get(date)
            if d is None:
                return ConsolidationStatus(date=date, status="pending")
            return ConsolidationStatus.from_dict(d)

    def set_running(self, date: str) -> bool:
        """设某日为 running；done/running 拒重入，pending/failed 允许。

        failed 重入时**保留** ``succeeded_ts``（重试幂等去重依据），不清空——
        重跑跳过已成功碎片，避免重复入图（ingest 不幂等）。
        """
        with self._lock:
            existing = self._data.get(date, {})
            status = existing.get("status", "pending")
            if status in ("done", "running"):
                return False
            # failed 重入：保留已成功碎片 ts（重跑跳过，幂等）；pending 新建：空 ts 集合。
            succeeded_ts = list(existing.get("succeeded_ts", [])) if status == "failed" else []
            self._data[date] = {
                "date": date,
                "status": "running",
                "events": existing.get("events", 0),
                "consolidated_at": datetime.now().isoformat(),
                "failures": 0,
                "succeeded_ts": succeeded_ts,
            }
            self._save()
            return True

    def set_done(self, date: str, events: int) -> None:
        """设某日为 done + 事件数（全成功，清空 succeeded_ts/failures）。"""
        with self._lock:
            self._data[date] = {
                "date": date,
                "status": "done",
                "events": events,
                "consolidated_at": datetime.now().isoformat(),
                "failures": 0,
                "succeeded_ts": [],
            }
            self._save()

    def set_failed(
        self,
        date: str,
        failures: int = 0,
        succeeded_ts: Optional[list[str]] = None,
    ) -> None:
        """设某日为 failed，记录失败条数 + 已成功碎片 ts（供重试幂等去重）。

        持久化已成功 ts——下次重跑 ``set_running``(failed) 会保留它们、跳过对应碎片，
        不重复入图。``events`` = 已成功碎片数（含历史），让"部分成功"可见。
        """
        with self._lock:
            existing = self._data.get(date, {})
            prev_ts = list(existing.get("succeeded_ts", []))
            new_ts = prev_ts + [ts for ts in (succeeded_ts or []) if ts not in prev_ts]
            self._data[date] = {
                "date": date,
                "status": "failed",
                "events": len(new_ts),
                "consolidated_at": datetime.now().isoformat(),
                "failures": failures,
                "succeeded_ts": new_ts,
            }
            self._save()

    def get_all(self) -> list[ConsolidationStatus]:
        """获取所有已知日期的状态。"""
        with self._lock:
            return [ConsolidationStatus.from_dict(d) for d in self._data.values()]


# --- 去噪接口 ---

class Denoiser(Protocol):
    """去噪判定器：逐碎片判「值得记 / 噪声」。

    实现应保守——拿不准就保留（不误杀）。只判去留，不合成、不归并、不抽概念。
    """

    def __call__(self, content: str) -> bool:
        """返回 True = 保留，False = 噪声丢弃。"""
        ...


class _DefaultDenoiser:
    """默认去噪器：保留全部（无 LLM 时退化为全保留）。"""

    def __call__(self, content: str) -> bool:
        return True


class LLMDenoiser:
    """LLM 去噪器：逐碎片调 LLM 判去留。

    保守策略——拿不准就保留。LLM 调用在 worker 线程外执行（不阻塞 MCS 单 worker）。
    LLM 不可用时退化为全保留。

    Args:
        llm: agent 的 LLM 后端（需暴露 chat 方法）。
    """

    def __init__(self, llm: Any) -> None:
        self._llm = llm

    def __call__(self, content: str) -> bool:
        """调用 LLM 判定碎片是否保留。LLM 失败时保守保留。"""
        try:
            messages = [
                {"role": "system", "content": "你是碎片去噪判定器。"},
                {"role": "user", "content": DENOISE_PROMPT.format(content=content)},
            ]
            response = self._llm.chat(messages, [])
            if hasattr(response, "content"):
                text = response.content or ""
            elif isinstance(response, dict):
                text = response.get("content", "")
            else:
                text = str(response)
            return "丢弃" not in text.strip()
        except Exception:
            logger.warning("去噪 LLM 调用失败，保守保留", exc_info=True)
            return True


# --- MemoryStore 协议（避免直接依赖） ---


class _MemoryStoreProto(Protocol):
    def ingest_structured(self, content: str, timestamp: str) -> str: ...


# --- FragmentStore 协议 ---


class _FragmentStoreProto(Protocol):
    def read(self, date: str) -> Optional[str]: ...


# --- 整合主流程 ---


class Consolidator:
    """整合管线：解析 → 去噪 → 逐条 ingest_structured。

    Args:
        fragment_store: 碎片存储（Slice 1 FragmentStore）。
        memory: 记忆底座（需暴露 ingest_structured）。
        tracker: 整合状态追踪。
        denoiser: 去噪判定器；None 用默认（全保留）。
    """

    def __init__(
        self,
        fragment_store: Any,
        memory: Any,
        tracker: ConsolidationTracker,
        denoiser: Optional[Denoiser] = None,
    ) -> None:
        self._fragments = fragment_store
        self._memory = memory
        self._tracker = tracker
        self._denoiser: Denoiser = denoiser or _DefaultDenoiser()
        self._mutex = threading.Lock()

    def consolidate(self, date: str) -> dict:
        """整合指定日期的碎片入图。

        Returns:
            {"ok": bool, "date": str, "status": str, "events": int, "warning": str | None}
        """
        # 互斥锁：同一时刻只允许一个整合
        if not self._mutex.acquire(blocking=False):
            return {"ok": False, "date": date, "status": "running", "events": 0,
                    "warning": "整合正在进行中"}

        try:
            return self._do_consolidate(date)
        finally:
            self._mutex.release()

    def _do_consolidate(self, date: str) -> dict:
        """实际整合逻辑（已持互斥锁）。"""
        # 单日锁定：done/running 拒；failed 允许重入（set_running 保留 succeeded_ts）。
        if not self._tracker.set_running(date):
            status = self._tracker.get(date)
            # set_running 返回 False 仅在 done / running；区分语义：
            # running → 正在整合中；done → 已整合（already）。
            return_status = "running" if status.status == "running" else "already"
            return {
                "ok": True,
                "date": date,
                "status": return_status,
                "events": status.events,
                "warning": None,
            }

        try:
            # 0. 取已成功碎片 ts（failed 重入时保留，作幂等去重依据）
            prev_succeeded = set(self._tracker.get(date).succeeded_ts)

            # 1. 读取碎片
            md_text = self._fragments.read(date) or ""

            # 2. 解析
            parsed = parse_fragments(md_text, date)

            # 3. 去噪（不改写 content，仅判去留——见去噪 requirement）
            retained: list[tuple[str, str]] = []
            for ts, content in parsed:
                if self._denoiser(content):
                    retained.append((ts, content))

            # 4. 跳过已成功碎片（重试幂等）+ 逐条 ingest（失败计数，不再吞掉掩盖为 done）
            to_ingest = [(ts, content) for (ts, content) in retained if ts not in prev_succeeded]
            succeeded_now: list[str] = []
            failures = 0
            for ts, content in to_ingest:
                try:
                    self._memory.ingest_structured(content, ts)
                    succeeded_now.append(ts)
                except Exception:
                    failures += 1
                    logger.error("ingest_structured 失败: date=%s, ts=%s", date, ts,
                                 exc_info=True)

            # 5. 判定终态：有失败 → failed（持久化已成功 ts，可重试幂等去重）；
            #    全成功 → done。让"部分失败"可见，不再掩盖为 done。
            all_succeeded = list(prev_succeeded) + succeeded_now
            if failures > 0:
                self._tracker.set_failed(
                    date, failures=failures, succeeded_ts=succeeded_now
                )
                return {
                    "ok": True,
                    "date": date,
                    "status": "failed",
                    "events": len(all_succeeded),
                    "failures": failures,
                    "warning": (
                        f"部分碎片入库失败（{failures} 条）；可重新整合补整——"
                        f"已成功的 {len(all_succeeded)} 条不会重复入图（幂等去重）"
                    ),
                }

            self._tracker.set_done(date, len(all_succeeded))
            return {
                "ok": True,
                "date": date,
                "status": "done",
                "events": len(all_succeeded),
                "warning": None,
            }

        except Exception:
            # 整体崩溃（read/parse 等）：保留已成功 ts，标 failed。
            self._tracker.set_failed(date)
            logger.error("整合失败: date=%s", date, exc_info=True)
            raise

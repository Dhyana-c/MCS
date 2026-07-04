"""整合调度器——APScheduler 进程内定时整合。

默认 cron ``30 0 * * *``（每天 00:30）整合**前一日**碎片。
可配 / 可禁用。整合互斥。随 FastAPI app lifespan 起停。
"""

from __future__ import annotations

import logging
import time
from datetime import date, timedelta
from typing import Any

__all__ = ["ConsolidationScheduler"]

logger = logging.getLogger(__name__)


class ConsolidationScheduler:
    """定时整合调度器（封装 APScheduler BackgroundScheduler）。

    Args:
        consolidator: Consolidator 实例（负责实际整合）。
        cron: cron 表达式（默认 ``30 0 * * *``，每天 00:30 整合昨天）。
            None 或空字符串表示禁用定时。
        enabled: 是否启用；False 不注册定时任务。
    """

    def __init__(
        self,
        consolidator: Any,
        cron: str = "30 0 * * *",
        enabled: bool = True,
    ) -> None:
        self._consolidator = consolidator
        self._cron = cron
        self._enabled = enabled and bool(cron)
        self._scheduler: Any = None

    def start(self) -> None:
        """启动调度器（注册定时任务）。"""
        if not self._enabled:
            logger.info("整合调度器已禁用，不注册定时任务")
            return

        try:
            from apscheduler.schedulers.background import BackgroundScheduler
        except ImportError:
            logger.warning(
                "apscheduler 未安装，定时整合不可用；pip install apscheduler"
            )
            return

        # cron 来自 env（MCS_CONSOLIDATION_CRON），配错不应炸掉整个 app 启动
        # （start 在 lifespan 里跑）——降级为禁用 + 显式报错。
        try:
            cron_kwargs = self._parse_cron(self._cron)
        except ValueError:
            logger.error("无效 cron 表达式 %r，定时整合未启用", self._cron)
            return

        self._scheduler = BackgroundScheduler()
        self._scheduler.add_job(
            self._run_yesterday,
            "cron",
            **cron_kwargs,
            id="consolidation_daily",
            replace_existing=True,
        )
        self._scheduler.start()
        logger.info("整合调度器已启动: cron=%s", self._cron)

    def shutdown(self, wait: bool = True) -> None:
        """关闭调度器。"""
        if self._scheduler is not None:
            self._scheduler.shutdown(wait=wait)
            logger.info("整合调度器已关闭")

    def _run_yesterday(self) -> None:
        """兜底确认昨天剩余 pending 碎片（定时任务回调）。"""
        yesterday = (date.today() - timedelta(days=1)).isoformat()
        t0 = time.perf_counter()
        try:
            result = self._consolidator.consolidate(yesterday)
            elapsed = time.perf_counter() - t0
            logger.info(
                "Consolidation done: date=%s, confirmed=%d, skipped=%d, failed=%d, elapsed=%.1fs",
                yesterday,
                result.get("confirmed", 0),
                result.get("skipped", 0),
                result.get("failed", 0),
                elapsed,
            )
        except Exception:
            elapsed = time.perf_counter() - t0
            logger.error(
                "Consolidation failed: date=%s, elapsed=%.1fs",
                yesterday,
                elapsed,
                exc_info=True,
            )

    @staticmethod
    def _parse_cron(cron_expr: str) -> dict:
        """将 5 字段 cron 表达式解析为 APScheduler cron 参数。"""
        parts = cron_expr.strip().split()
        if len(parts) != 5:
            raise ValueError(f"无效 cron 表达式: {cron_expr!r}（需要 5 字段）")
        return {
            "minute": parts[0],
            "hour": parts[1],
            "day": parts[2],
            "month": parts[3],
            "day_of_week": parts[4],
        }

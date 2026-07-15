"""事件时间戳排序工具。

事件时间戳（``extensions.event_meta.timestamp``）按 **universe 内时间语义**存储
（work-narrative-events）：现实 universe 为 ISO 8601，作品 universe 为作品纪年
字符串（如"200 年"）。现实侧历史上存在两种 ISO 形态混存：本地裸时间（碎片确认
入图，``YYYY-MM-DDTHH:MM:SS``）与 UTC aware（旧 ``_now_iso``，``…+00:00``）。
**字典序对混合形态排序错误**——UTC+8 下同一真实时刻的两种写法字典序相差 8 小时，
会破坏 recall 时间倒排与背书事件截取。

因此时间倒排 MUST 经本模块解析为绝对时间（epoch 秒）比较：naive 视为本地时区、
aware 按自带时区换算。非 ISO 的作品纪年走**数字年最小解析**（"200 年" / "184" →
首个整数作可比数值；Phase 1 仅数字年可排，"建安五年"等混合纪年需 Phase 2 归一化）；
空 / 完全无数字的非法时间戳返回 -inf（倒排后垫底，保持旧行为）。排序全序保证
仅在单 universe 内成立（现实 ISO 或作品数字年，不混排）。
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

__all__ = ["timestamp_sort_value", "event_sort_key"]

_FIRST_INT = re.compile(r"\d+")


def timestamp_sort_value(timestamp: str | None) -> float:
    """把时间戳字符串转为可全序比较的数值（单 universe 内有效）。

    - ISO 8601 → epoch 秒：naive（无时区）视为**本地时间**（``datetime.timestamp()``
      的缺省语义）；aware 按自带时区换算为绝对时间；
    - 非 ISO（作品纪年）→ **数字年最小解析**：取字符串中首个整数（"200 年" → 200、
      "2043年1月" → 2043）。年粒度、同年失序（Phase 1 口径）；"建安五年"等
      非数字纪年无从解析 → -inf 垫底，Phase 2 纪年归一化后才可排；
    - 空 / 无数字的非法值返回 ``float("-inf")``（``reverse=True`` 倒排后排在末尾）。

    注意：epoch 秒与数字年是两把尺子——跨 universe 混排无意义（时间全序仅在单
    universe 内保证，与宪法"每 universe 一条独立时间轴"一致）。
    """
    if not timestamp:
        return float("-inf")
    try:
        dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError:
        m = _FIRST_INT.search(timestamp)
        if m:
            return float(m.group())  # 数字年最小解析（"200 年" → 200.0）
        return float("-inf")
    return dt.timestamp()


def event_sort_key(node: Any) -> tuple[float, str]:
    """事件节点时间排序键 ``(epoch 秒, id)``——id 作次级键保排序确定性。

    读 ``extensions.event_meta.timestamp``；配合 ``sort(reverse=True)`` 即时间倒排、
    无 / 非法时间戳垫底。``get_related_events`` 各实现与 recall MUST 共用本键，
    保证混合形态时间戳（本地裸时间 vs UTC aware）也能正确全序。
    """
    meta = (getattr(node, "extensions", None) or {}).get("event_meta", {})
    ts = meta.get("timestamp", "") if isinstance(meta, dict) else ""
    return (timestamp_sort_value(ts), node.id)

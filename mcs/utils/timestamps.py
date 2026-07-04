"""事件时间戳排序工具。

事件时间戳（``extensions.event_meta.timestamp``）在图中以 ISO 8601 字符串存储，
历史上存在两种形态混存：本地裸时间（碎片确认入图，``YYYY-MM-DDTHH:MM:SS``）与
UTC aware（旧 ``_now_iso``，``…+00:00``）。**字典序对混合形态排序错误**——UTC+8 下
同一真实时刻的两种写法字典序相差 8 小时，会破坏 recall 时间倒排与背书事件截取。

因此时间倒排 MUST 经本模块解析为绝对时间（epoch 秒）比较：naive 视为本地时区、
aware 按自带时区换算；空 / 非法时间戳返回 -inf（倒排后垫底，保持旧行为）。
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

__all__ = ["timestamp_sort_value", "event_sort_key"]


def timestamp_sort_value(timestamp: str | None) -> float:
    """把 ISO 8601 时间戳转为可全序比较的 epoch 秒。

    - naive（无时区）视为**本地时间**（``datetime.timestamp()`` 的缺省语义）；
    - aware 按自带时区换算为绝对时间；
    - 空 / 非法返回 ``float("-inf")``（``reverse=True`` 倒排后排在末尾）。
    """
    if not timestamp:
        return float("-inf")
    try:
        dt = datetime.fromisoformat(timestamp.replace("Z", "+00:00"))
    except ValueError:
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

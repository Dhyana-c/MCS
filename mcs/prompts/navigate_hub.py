"""Prompt bundle for purpose='navigate_hub'.

Used by ``HubFallbackEntryPlugin`` (when alias/timeseries entries return
empty) to navigate top-down from root hubs. Also used by write pipeline ②
when there are no anchors at all. Output: subset of children ids to drill
into (empty list = stop, this is the target region).
"""

from __future__ import annotations

import json

from mcs.core.errors import LLMParseError
from mcs.utils.text_utils import strip_json_fence

SYSTEM_PROMPT = (
    "你从一个上位枢纽出发，判断该往哪一个或几个下属分支下钻才能接近目标。"
    "若当前位置已经是目标所在区域、不需要再下钻，返回空数组。"
)

USER_TEMPLATE = (
    "目标:\n{target}\n\n"
    "当前位置和下属分支:\n{material}\n\n"
    "请返回该下钻的下属 id 列表 JSON; "
    "若当前已到位则返回 []。只返回 JSON。"
)


def parse(raw: str) -> list[str]:
    try:
        data = json.loads(strip_json_fence(raw))
    except json.JSONDecodeError as e:
        raise LLMParseError("navigate_hub", raw, str(e)) from e
    if not isinstance(data, list) or not all(isinstance(x, str) for x in data):
        raise LLMParseError(
            "navigate_hub", raw, "expected JSON array of strings"
        )
    return data

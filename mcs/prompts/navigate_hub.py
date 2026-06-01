"""purpose='navigate_hub' 的 Prompt 包。

用于 ``HubFallbackEntryPlugin``（当别名/时序入口返回空时）
从根枢纽自顶向下导航。也用于写入管线阶段 ②（完全没有锚点时）。
输出：要下钻的子节点 id 子集（空列表表示停止，当前位置就是目标区域）。
"""

from __future__ import annotations

import json
import re

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


# 抢救已闭合的带引号字符串：用于 LLM 输出因 max_tokens 截断成未闭合 JSON 数组时的容错
_QUOTED_STR = re.compile(r'"((?:[^"\\]|\\.)*)"')


def _salvage_quoted_strings(text: str) -> list[str]:
    """从（可能被截断的）JSON 文本里抽出所有**已闭合**的带引号字符串。

    LLM 输出超过 max_tokens 被截断时，JSON 数组末尾会残留未闭合的串；正则只匹配
    成对引号，天然丢弃被截断的尾部残片。下游会用 ``get_node`` 再过滤掉无效 id。
    """
    return [m.group(1) for m in _QUOTED_STR.finditer(text)]


def parse(raw: str) -> list[str]:
    cleaned = strip_json_fence(raw)
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError as e:
        # 容错：LLM 输出可能因 max_tokens 截断成未闭合 JSON 数组（hub 候选过多时常见）。
        # 抢救已闭合的 id；抢救到就用，完全抢救不到才保持原 raise 行为。
        salvaged = _salvage_quoted_strings(cleaned)
        if salvaged:
            return salvaged
        raise LLMParseError("navigate_hub", raw, str(e)) from e
    if not isinstance(data, list) or not all(isinstance(x, str) for x in data):
        raise LLMParseError(
            "navigate_hub", raw, "expected JSON array of strings"
        )
    return data

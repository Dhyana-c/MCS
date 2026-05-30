"""Prompt bundle for purpose='decide_directions'.

Stage ③ of the read pipeline (semantic loop). Input: focus node +
neighbors + accumulated. Output: List[node_id] to expand toward (may be
empty if no direction looks promising).

Key principle: "判方向，不判局部相关"——the LLM picks neighbors that
LEAD toward the query, not neighbors that are themselves directly relevant.
"""

from __future__ import annotations

import json

from mcs.core.errors import LLMParseError
from mcs.utils.text_utils import strip_json_fence

SYSTEM_PROMPT = (
    "你判断从当前节点出发，沿哪些邻居扩展能通向查询想要的答案。"
    "不要只看邻居本身和查询相不相关——看它背后可能挂着什么。"
    "已经捞到的内容不要重复纳入。"
)

USER_TEMPLATE = (
    "查询:\n{query}\n\n"
    "当前节点和邻居:\n{material}\n\n"
    "已捞到的节点摘要:\n{accumulated}\n\n"
    "请返回该继续扩展的邻居 id 列表 JSON, 例如 [\"id_a\", \"id_b\"]; "
    "若没有合适方向则返回 []。只返回 JSON。"
)


def parse(raw: str) -> list[str]:
    try:
        data = json.loads(strip_json_fence(raw))
    except json.JSONDecodeError as e:
        raise LLMParseError("decide_directions", raw, str(e)) from e
    if not isinstance(data, list) or not all(isinstance(x, str) for x in data):
        raise LLMParseError(
            "decide_directions", raw, "expected JSON array of strings"
        )
    return data

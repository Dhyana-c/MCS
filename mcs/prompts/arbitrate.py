"""Prompt bundle for purpose='arbitrate'.

Optional stage ④ of the read pipeline (LLMArbitrationPlugin). Input:
accumulated nodes that may include conflicting versions. Output: list of
node ids forming a self-consistent subset for this query.
"""

from __future__ import annotations

import json

from mcs.core.errors import LLMParseError
from mcs.utils.text_utils import strip_json_fence

SYSTEM_PROMPT = (
    "你从一堆已经捞到的相关节点里，选出与查询自洽、不互相矛盾的一组。"
    "如果查询问「现在/最新」，取当前未过时的；"
    "如果查询问「曾经/历史」，可以保留多版本；"
    "如果有「同槽位互斥」（如同一属性的两个互斥值），只留一个。"
)

USER_TEMPLATE = (
    "查询:\n{query}\n\n"
    "候选节点（含 id、名称、相关说法）:\n{material}\n\n"
    "请返回保留的节点 id 列表 JSON。只返回 JSON。"
)


def parse(raw: str) -> list[str]:
    try:
        data = json.loads(strip_json_fence(raw))
    except json.JSONDecodeError as e:
        raise LLMParseError("arbitrate", raw, str(e)) from e
    if not isinstance(data, list) or not all(isinstance(x, str) for x in data):
        raise LLMParseError("arbitrate", raw, "expected JSON array of strings")
    return data

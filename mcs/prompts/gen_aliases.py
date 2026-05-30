"""Prompt bundle for purpose='gen_aliases'.

Used when a new concept is created. Input: the concept (single node).
Output: a list of alias strings (synonyms, abbreviations, common
mis-spellings) that get registered in the alias index.
"""

from __future__ import annotations

import json

from mcs.core.errors import LLMParseError
from mcs.utils.text_utils import strip_json_fence

SYSTEM_PROMPT = (
    "你为给定概念生成别名集合：同义词、缩写、常见说法、易错写法。"
    "只输出真实可能被使用的别名，不要硬凑。"
)

USER_TEMPLATE = (
    "概念:\n{material}\n\n"
    "请返回别名字符串列表 JSON, 例如 [\"AAPL\", \"苹果公司\", \"苹果\"]。"
    "只返回 JSON。"
)


def parse(raw: str) -> list[str]:
    try:
        data = json.loads(strip_json_fence(raw))
    except json.JSONDecodeError as e:
        raise LLMParseError("gen_aliases", raw, str(e)) from e
    if not isinstance(data, list) or not all(isinstance(x, str) for x in data):
        raise LLMParseError("gen_aliases", raw, "expected JSON array of strings")
    return data

"""purpose='gen_aliases' 的 Prompt 包。

输入：概念（单个节点）。输出：别名字符串列表（同义词、缩写、常见拼写错误），
用于注册到别名索引。

注意：Phase 1 默认流程并不自动调用 ``gen_aliases``——它作为开箱即用的默认
prompt 保留，供用户在自定义压缩/后置插件中通过 ``llm_caller`` 触发，或整组覆盖。
"""

from __future__ import annotations

import json

from mcs.core.errors import LLMParseError
from mcs.utils.text_utils import strip_json_fence

SYSTEM_PROMPT = (
    "你为给定概念生成别名集合：同义词、缩写、常见说法、易错写法。"
    "只输出真实可能被使用的别名，不要硬凑。"
    "\n\n**语言跟随**：别名 MUST 是该概念在**原文语言**下的同义词/缩写/变体写法，"
    "MUST NOT 给跨语言「对译」（英文概念只给英文别名、中文概念只给中文别名）——"
    "对译是另一语种节点的事，混入会污染别名索引、致跨语种误召回。"
)

USER_TEMPLATE = (
    "概念:\n{material}\n\n"
    "请返回该概念在原语言下的别名字符串列表 JSON，例如 [\"US\", \"United States\", \"America\"]。"
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

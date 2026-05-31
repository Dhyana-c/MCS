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

"""purpose='decide_directions' 的 Prompt 包。

查询管线阶段 ③（语义循环）。输入：焦点节点 + 邻域 + 已累积节点。
输出：List[node_id] 要扩展的方向（如果没有合适方向可返回空列表）。

核心原则："判方向，不判局部相关"——LLM 选的是通向答案的邻居，
不是本身直接相关的邻居。
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

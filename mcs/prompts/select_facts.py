"""purpose='select_facts' 的 Prompt 包。

用于查询管线阶段 ③ 事实 BFS 遍历：输入候选节点 + 事实边（统一编号平铺），
LLM 从中选出与查询相关的编号列表。

替代旧的 select_nodes（只选节点、不浮现事实）。
"""

from __future__ import annotations

import json

from mcs.core.errors import LLMParseError
from mcs.utils.text_utils import strip_json_fence

SYSTEM_PROMPT = (
    "你从候选事实条目中选出与查询最相关的条目编号。"
    "事实条目包括概念节点和关系事实（格式：主 —label→ 宾）。"
    "选中的编号对应你需要的事实条目，返回编号列表即可。"
    "优先选择直接回答查询的事实，优先选择具体信息而非笼统概括。"
    "已经选过的内容不要重复纳入。"
)

USER_TEMPLATE = (
    "查询:\n{query}\n\n"
    "候选事实条目（编号统一，节点在前、事实边在后）:\n"
    "{material}\n\n"
    "已选内容摘要:\n{accumulated_summary}\n\n"
    "请返回与查询最相关的事实条目**编号**列表 JSON，例如 [1, 3, 5]；"
    "若没有相关条目则返回 []。按相关性降序排列。只返回 JSON。"
)


def parse(raw: str) -> list[int]:
    """解析 LLM 返回的编号列表。

    Returns:
        选中条目的编号列表（int）。
    """
    try:
        data = json.loads(strip_json_fence(raw))
    except json.JSONDecodeError as e:
        raise LLMParseError("select_facts", raw, str(e)) from e
    if not isinstance(data, list) or not all(isinstance(x, int) for x in data):
        raise LLMParseError(
            "select_facts", raw, "expected JSON array of integers"
        )
    return data

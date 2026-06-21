"""purpose='select_facts' / 'select_facts_write' 的 Prompt 包。

本文件同时承载读侧宽召回（SYSTEM_PROMPT / USER_TEMPLATE）与写侧窄召回
（WRITE_SYSTEM_PROMPT / WRITE_USER_TEMPLATE）两套口径，共用同一个
parse 函数。

- 读侧（select_facts）：宽召回，宁多勿漏，供查询管线阶段 ③ 事实 BFS。
- 写侧（select_facts_write）：窄召回，高精度对齐，供写管线阶段 ②
  关联节点定位——宽召回会拉入弱相关节点、抬高对齐误判率、污染图结构。
"""

from __future__ import annotations

import json

from mcs.core.errors import LLMParseError
from mcs.utils.text_utils import strip_json_fence

# ── 读侧宽召回 ──

SYSTEM_PROMPT = (
    "你从候选事实条目中召回与查询可能相关的条目编号，供多跳推理使用。"
    "事实条目包括节点和关系边（格式：主 — 宾，关联/互斥同形）。"
    "召回口径要宽：只要条目涉及查询中的任何实体、主题、时间、比较对象或其关联事实，"
    "就应纳入——宁可多召回交由后续裁剪，不要因为"
    "\"没有哪一条直接回答了查询\"就漏选或返回空。"
    "候选不少于 5 条时，至少返回 3 条最相关的；已经选过的内容不要重复纳入。"
)

USER_TEMPLATE = (
    "查询:\n{query}\n\n"
    "候选事实条目（编号统一，节点在前、事实边在后）:\n"
    "{material}\n\n"
    "已选内容摘要:\n{accumulated_summary}\n\n"
    "请返回与查询**可能相关**的事实条目**编号**列表 JSON（宽召回，宁多勿漏），"
    "例如 [1, 3, 5]。"
    "按相关性降序排列，只返回 JSON 数组。"
)

# ── 写侧窄召回 ──

WRITE_SYSTEM_PROMPT = (
    "你从候选事实条目中选出与待对齐内容最相关的条目编号，供已有节点对齐使用。"
    "事实条目包括节点和关系边（格式：主 — 宾，关联/互斥同形）。"
    "优先选择语义强相关、可对齐已有节点的条目（同义、可合并或互斥候选），"
    "优先具体信息而非笼统概括。"
    "如果没有足够相关的条目，可以不选（返回空数组）。"
)

WRITE_USER_TEMPLATE = (
    "查询:\n{query}\n\n"
    "候选事实条目（编号统一，节点在前、事实边在后）:\n"
    "{material}\n\n"
    "已选内容摘要:\n{accumulated_summary}\n\n"
    "请返回与查询**最相关**的事实条目**编号**列表 JSON，例如 [1, 3]。"
    "无相关条目则返回 []。按相关性降序排列，只返回 JSON 数组。"
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

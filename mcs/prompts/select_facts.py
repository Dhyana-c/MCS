"""purpose='select_facts_write' 的 Prompt 包（写管线关联定位窄召回）。

读侧 ``select_facts`` 宽召回 bundle（SYSTEM_PROMPT / USER_TEMPLATE）已随读查询编排
退役删除（见 ``retire-framework-query-pipeline``）——查询职责归记忆 agent 的分步游走，
不再有读路径事实 BFS。本文件仅保留：

- 写侧窄召回（WRITE_SYSTEM_PROMPT / WRITE_USER_TEMPLATE）：供写管线阶段 ② 关联节点
  定位（``query_nodes`` → ``_traverse(select_purpose="select_facts_write")``）。
  宽召回会拉入弱相关节点、抬高对齐误判率、污染图结构，故写侧用窄召回。
  写侧输出 **flat 编号数组**，由 ``parse`` 归一为"两者"（result == frontier）。
- ``SelectFactsResult`` / ``coerce_select_result`` / ``parse``：数据类与解析（写侧
  ``_traverse`` 仍用 ``coerce_select_result`` 把 flat 数组归一为双角色）。
"""

from __future__ import annotations

import json
from typing import Any, NamedTuple

from mcs.core.errors import LLMParseError
from mcs.utils.text_utils import strip_json_fence


class SelectFactsResult(NamedTuple):
    """select_facts 双角色选择结果（1-based 编号列表）。

    - ``result``：进 accumulated（吃 T、为返回集）的条目编号。
    - ``frontier``：进 frontier（不吃 T、驱动下一跳 BFS）的条目编号。
    同一编号可同时出现在两者（= "两者"角色）。
    """

    result: list[int]
    frontier: list[int]


# ── 写侧窄召回（flat 数组，parse 归一为"两者"）──

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


def _as_int_list(value: Any, raw: str) -> list[int]:
    """校验 value 为 int 列表，否则抛 LLMParseError。"""
    if not isinstance(value, list) or not all(isinstance(x, int) for x in value):
        raise LLMParseError(
            "select_facts", raw, "expected JSON array of integers"
        )
    return value


def coerce_select_result(obj: Any, raw: str = "") -> SelectFactsResult:
    """把 LLM 输出（已解码）归一为 ``SelectFactsResult``。

    - 已是 ``SelectFactsResult`` → 原样返回。
    - ``dict`` → 读 ``result`` / ``frontier`` 两列表（缺省空）。
    - ``list[int]`` → flat 数组，归一为 ``result == frontier`` 该数组（"两者"）。
    - 其他 → 抛 ``LLMParseError``。
    """
    if isinstance(obj, SelectFactsResult):
        return obj
    if isinstance(obj, dict):
        result = _as_int_list(obj.get("result", []), raw)
        frontier = _as_int_list(obj.get("frontier", []), raw)
        return SelectFactsResult(result, frontier)
    if isinstance(obj, list):
        flat = _as_int_list(obj, raw)
        return SelectFactsResult(list(flat), list(flat))
    raise LLMParseError(
        "select_facts", raw, "expected JSON object or array of integers"
    )


def parse(raw: str) -> SelectFactsResult:
    """解析 LLM 返回为双角色选择结果。

    Returns:
        ``SelectFactsResult(result, frontier)``（1-based 编号列表）。
    """
    try:
        data = json.loads(strip_json_fence(raw))
    except json.JSONDecodeError as e:
        raise LLMParseError("select_facts", raw, str(e)) from e
    return coerce_select_result(data, raw)

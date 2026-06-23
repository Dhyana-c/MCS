"""purpose='select_facts' / 'select_facts_write' 的 Prompt 包。

本文件同时承载读侧宽召回（SYSTEM_PROMPT / USER_TEMPLATE）与写侧窄召回
（WRITE_SYSTEM_PROMPT / WRITE_USER_TEMPLATE）两套口径，共用同一个
parse 函数。

- 读侧（select_facts）：**双角色**输出——`探索`（宽召回，进 frontier、驱动 BFS）
  + `结果`（精筛，进 accumulated、为返回集）。供查询管线阶段 ③ 事实 BFS。
- 写侧（select_facts_write）：窄召回，高精度对齐，供写管线阶段 ②
  关联节点定位——宽召回会拉入弱相关节点、抬高对齐误判率、污染图结构。
  写侧仍输出 **flat 编号数组**，由 ``parse`` 归一为"两者"（result == frontier），
  写路径行为逐字等价。

parse 返回 ``SelectFactsResult(result, frontier)``：
  - 读侧 LLM 输出 JSON 对象 ``{"result": [...], "frontier": [...]}``，编号同时
    出现在两列表 = "两者"。
  - 旧式 flat 数组 ``[1, 3, 5]``（写侧 / 读侧 LLM 偶发不遵守新格式）→ 归一为
    ``result == frontier ==`` 该数组（安全退化为旧行为：选中即进双方）。
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


# ── 读侧双角色（V4 定稿：宽探索 + 严结果 + 任务背景）──
# GLM-5.1 验证此版 gold 5/6 + accumulated 精筛 16-78（双角色理想态）；
# deepseek-chat 守不住精细口径（空返回/膨胀两难），生产可切 V3（拿不准归 result，
# gold 4/6 但 accumulated 胀）。多版本 prompt 实验、模型差异、版本切换策略见
# docs/select_facts_model_differences.md。

SYSTEM_PROMPT = (
    "你在为一个多跳问答系统做知识图检索。知识图里节点是概念 / 事实 / 事件，"
    "边（关联）连起它们。用户问一个问题，系统从问题里的实体出发，沿关联边一跳一跳"
    "地往外搜证据——这就是你在做的事。\n\n"
    "当前这一步：系统正站在某个节点上，把它的邻居（候选事实条目）摆给你，"
    "让你判断哪些值得要。把候选分两类：\n"
    "- result（**和查询有关**）：确定与问题相关的条目——直接涉及问题问的实体、主题、"
    "事件，或能支撑回答。这些会**进入答案上下文**。\n"
    "- frontier（**和查询可能有关**）：间接相关、可能有用、值得顺着查的条目——"
    "问题实体的关联概念、时间线邻居、比较对象的背景等。这些会作为**下一跳的起点**，"
    "继续往外搜（多跳的'多'就靠它们往外扩）。\n\n"
    "为什么分两类：单跳往往凑不齐完整答案，frontier 让搜索往外扩，多跳之后才能召回"
    "更多 result。所以 result 要准（直接进答案），frontier 要宽（保多跳探索不漏）。\n"
    "**绝不返回空**——只要候选里有任何条目和查询沾边，就必须归类；"
    "禁止返回 [] 或 {\"result\":[],\"frontier\":[]}。\n"
    "事实条目含节点和关系边（关系边格式：主 — 宾，关联/互斥同形）。"
    "一个条目可同时归两类（确定相关又值得继续查）。\n"
    "**硬性下限**：候选 ≥ 3 条时，result 至少 1 条、frontier 至少 3 条；"
    "候选 < 3 条时把相关的都归 result。已选过的不重复纳入。"
)

USER_TEMPLATE = (
    "查询:\n{query}\n\n"
    "候选事实条目（编号统一，节点在前、事实边在后）:\n"
    "{material}\n\n"
    "已选内容摘要:\n{accumulated_summary}\n\n"
    "**必须**返回 JSON 对象（不是裸数组），两个列表都尽量非空：\n"
    "{{\"result\": [和查询有关的编号...], "
    "\"frontier\": [和查询可能有关的编号...]}}\n"
    "- result：确定与查询相关的条目（拿不准也归这里）\n"
    "- frontier：可能相关、值得顺着查的条目\n"
    "示例：{{\"result\": [1, 3], \"frontier\": [1, 2, 3, 5]}}\n"
    "禁止返回 [] 或 {{\"result\":[], \"frontier\":[]}}。只返回该 JSON 对象。"
)

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

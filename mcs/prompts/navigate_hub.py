"""purpose='navigate_hub' 的 Prompt 包。

用于 ``HubFallbackEntryPlugin``（当别名/时序入口返回空时）
从根枢纽自顶向下导航。也用于写入管线阶段 ②（完全没有锚点时）。
输出：要下钻的子节点 id 子集（空列表表示停止，当前位置就是目标区域）。
"""

from __future__ import annotations

import json
import re

from mcs.utils.text_utils import strip_json_fence

SYSTEM_PROMPT = (
    "你从一个上位枢纽出发，判断该往哪一个或几个下属分支下钻才能接近目标。"
    "若当前位置已经是目标所在区域、不需要再下钻，返回空数组。"
)

USER_TEMPLATE = (
    "目标:\n{target}\n\n"
    "当前位置和下属分支:\n{material}\n\n"
    "请返回该下钻的下属 id 列表 JSON; "
    "若当前已到位则返回 []。只返回 JSON。"
)


# navigate_hub 本应返回「节点 id 的 JSON 字符串数组」，但 LLM 输出常不规整：可能带前缀
# （"JSON:"）、用对象数组（[{"id":..}]）、用对象包裹（{"ids":[..]}）、或被 max_tokens 截断。
# parser 尽量从中抽出 id 列表；实在抽不出则返回 []（视为「无下钻目标」，优雅降级，**绝不**
# 因格式问题抛异常拖垮整条 query）。下游会用 ``get_node`` 过滤掉无效 id。

_QUOTED_STR = re.compile(r'"((?:[^"\\]|\\.)*)"')
_ID_KEYS = ("id", "node_id", "nodeId", "target", "target_id", "node")


def _strip_prefix(text: str) -> str:
    """去掉 JSON 主体前的说明性前缀（如 ``JSON:``），从首个 ``[`` 或 ``{`` 起截取。"""
    s = text.strip()
    for i, ch in enumerate(s):
        if ch in "[{":
            return s[i:]
    return s


def _ids_from_dict(d: dict) -> list[str]:
    """从 dict 元素抽 id：优先 id-like 字段，否则退化为其所有非空字符串值。"""
    for key in _ID_KEYS:
        v = d.get(key)
        if isinstance(v, str) and v:
            return [v]
    return [v for v in d.values() if isinstance(v, str) and v]


def _coerce_to_ids(data: object) -> list[str]:
    """把已解析的 JSON（多种形态）归一为 id 字符串列表。"""
    if isinstance(data, str):
        return [data] if data else []
    if isinstance(data, dict):
        # 形如 {"ids": [...]} / {"drill": [...]}：取第一个列表值递归
        for v in data.values():
            if isinstance(v, list):
                return _coerce_to_ids(v)
        return _ids_from_dict(data)
    if isinstance(data, list):
        out: list[str] = []
        for x in data:
            if isinstance(x, str) and x:
                out.append(x)
            elif isinstance(x, dict):
                out.extend(_ids_from_dict(x))
        return out
    return []


def _salvage_quoted_strings(text: str) -> list[str]:
    """从（可能被截断的）JSON 文本里抽出所有**已闭合**的带引号字符串（截断兜底）。"""
    return [m.group(1) for m in _QUOTED_STR.finditer(text)]


def parse(raw: str) -> list[str]:
    """宽容解析 navigate_hub 输出为 id 列表；无法解析则返回 ``[]``（不抛异常）。"""
    cleaned = _strip_prefix(strip_json_fence(raw or ""))
    try:
        data = json.loads(cleaned)
    except json.JSONDecodeError:
        # 截断/脏 JSON → 抢救已闭合的字符串 id
        return _salvage_quoted_strings(cleaned)
    return _coerce_to_ids(data)

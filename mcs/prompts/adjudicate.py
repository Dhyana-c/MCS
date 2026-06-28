"""purpose='adjudicate' 的 Prompt 包。

记忆 agent 的 ``arbitrate`` 工具（仲裁·只读语义判断）**内部** purpose。输入：
若干互斥事实 + 各自背书事件 + 问题 / 语境。输出：``{"adopt": [采信的事实 id...],
"reason": "..."}``。

命名消歧（见 design D9）：本 ``adjudicate`` purpose 仅由 agent 的 ``arbitrate``
工具使用，与查询管线 ``LLMArbitrationPlugin`` 的 ``arbitrate`` purpose 同名不同域
（后者只返 ``list[str]``、不吃事件、语义是「按 query 选自洽子集」）。故新增
``adjudicate``、零侵入共享的 ``arbitrate`` purpose。

幻觉 id 过滤**不在**本 ``parse`` 做（``parse`` 不知传入事实 id 集合，只解析结构），
落在 ``MemoryStore._do_arbitrate`` 层（只保留传入事实 id）。
"""

from __future__ import annotations

import json

from mcs.core.errors import LLMParseError
from mcs.utils.text_utils import strip_json_fence

SYSTEM_PROMPT = (
    "你是一个事实裁决专家。给定若干相互矛盾 / 互斥的事实，以及各自的支持（背书）事件，"
    "判断应当采信哪个事实，并给出理由。"
    "同一槽位互斥的事实通常只应采信一个（除非证据明确表明多个都成立）。"
    "优先采信有更近期、更明确背书事件支持的事实。"
    "adopt 只能填入给定事实的 id，不要编造未提供的 id。"
)

USER_TEMPLATE = (
    "问题 / 语境:\n{query}\n\n"
    "互斥事实与各自背书事件:\n{material}\n\n"
    "请返回 JSON：\n"
    '{{"adopt": ["采信的事实 id"], "reason": "采信理由"}}\n'
    "只返回 JSON。"
)


def parse(raw: str) -> dict:
    """解析为 ``{"adopt": [str...], "reason": str}``。

    非法 JSON / 非 object / adopt 非字符串数组 → 抛 ``LLMParseError``。
    缺字段容错：``adopt`` 缺省 ``[]``、``reason`` 缺省 ``""``。
    """
    try:
        data = json.loads(strip_json_fence(raw))
    except json.JSONDecodeError as e:
        raise LLMParseError("adjudicate", raw, str(e)) from e
    if not isinstance(data, dict):
        raise LLMParseError("adjudicate", raw, "expected JSON object")

    adopt = data.get("adopt", [])
    if not isinstance(adopt, list) or not all(isinstance(x, str) for x in adopt):
        raise LLMParseError("adjudicate", raw, "adopt must be an array of strings")

    reason = data.get("reason", "")
    if not isinstance(reason, str):
        reason = str(reason)

    return {"adopt": list(adopt), "reason": reason}

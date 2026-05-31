"""purpose='decide_hub' 的 Prompt 包。

写入阶段 ⑥ FanoutReducer 压缩插件。输入：焦点节点 + 所有邻居（超出预算）。
输出：HubDecision —— 要么提拔一个现有邻居（hub_id 有值），
要么合成一个新枢纽（hub_id=None，synthetic_hub_summary 有值）。
"""

from __future__ import annotations

import json

from mcs.core.decisions import HubDecision
from mcs.core.errors import LLMParseError
from mcs.utils.text_utils import strip_json_fence

SYSTEM_PROMPT = (
    "你判断在一片密集的邻居社区里，哪个节点最适合当上位枢纽。"
    "优先提拔现有概念（它能收纳其余成员），实在没有合适的才合成一个枢纽。"
    "明确说出理由，不要随便挑。"
)

USER_TEMPLATE = (
    "当前节点和它的邻居社区:\n{material}\n\n"
    "请返回 JSON:\n"
    '  {{"hub_id": "<选中的邻居 id, 或 null 表示需要合成>",\n'
    '   "reason": "为什么是它/为什么需要合成",\n'
    '   "synthetic_hub_summary": "若 hub_id 为 null, 给一段摘要描述合成枢纽"}}\n'
    "只返回 JSON。"
)


def parse(raw: str) -> HubDecision:
    try:
        data = json.loads(strip_json_fence(raw))
    except json.JSONDecodeError as e:
        raise LLMParseError("decide_hub", raw, str(e)) from e
    if not isinstance(data, dict):
        raise LLMParseError("decide_hub", raw, "expected JSON object")
    return HubDecision(
        hub_id=data.get("hub_id"),
        reason=data.get("reason", "") or "",
        synthetic_hub_summary=data.get("synthetic_hub_summary"),
    )

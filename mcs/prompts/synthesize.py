"""purpose='synthesize' 的 Prompt 包。

查询管线阶段 ⑤ 后处理（当配置了 SynthesizePlugin 时）。
输入：最终选中的节点 + 原始查询。输出：自然语言答案字符串。
"""

from __future__ import annotations

from mcs.core.errors import LLMParseError

SYSTEM_PROMPT = (
    "你基于给定的图节点材料合成对用户查询的回答。"
    "只用材料中明确出现的内容，不编造未提及的细节。"
    "如果材料里有出处，简短带上。"
)

USER_TEMPLATE = (
    "查询:\n{query}\n\n"
    "材料:\n{material}\n\n"
    "请直接给出回答。"
)


def parse(raw: str) -> str:
    if not isinstance(raw, str):
        raise LLMParseError("synthesize", str(raw), "expected string response")
    return raw.strip()

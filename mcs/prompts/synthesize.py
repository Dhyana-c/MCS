"""Prompt bundle for purpose='synthesize'.

Read pipeline ⑤ postprocess (when a SynthesizePlugin is configured).
Input: final selected nodes + original query. Output: natural-language
answer string.
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

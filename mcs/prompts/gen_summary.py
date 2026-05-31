"""purpose='gen_summary' 的 Prompt 包。

用于 SummaryRegen 压缩插件。输入：单个节点的内容。
输出：紧凑摘要字符串，受 ``max_tokens`` 限制（通过 free_args 传入）。
"""

from __future__ import annotations

from mcs.core.errors import LLMParseError

SYSTEM_PROMPT = (
    "你为输入内容生成紧凑摘要，保留关键概念与定义，不要列表化、不要序号。"
)

USER_TEMPLATE = (
    "内容:\n{material}\n\n"
    "用 {max_tokens} 字以内总结，直接输出摘要文本。"
)


def parse(raw: str) -> str:
    if not isinstance(raw, str):
        raise LLMParseError("gen_summary", str(raw), "expected string response")
    return raw.strip()

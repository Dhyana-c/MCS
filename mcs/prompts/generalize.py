"""purpose='generalize' 的 Prompt 包。

记忆 agent 的 ``generalize`` 工具（归纳·只读语义判断）：给定若干节点，让 LLM
概括它们的公共上位概念 / 共性。输入：节点 material（由工具自建、T 有界、经
``free_args["material"]`` 显式传）+ 可选聚焦语境。输出：自由文本（概括结论）。

**不建节点、不改图**——与 ``decide_hub``（社区划分 + 结构化 ``MultiHubDecision``、
写入期结构重组）不同，本 purpose 只返回一段概括文本，供 agent 理解概念关系。
"""

from __future__ import annotations

from mcs.core.errors import LLMParseError

SYSTEM_PROMPT = (
    "你是一个知识归纳专家。给定若干节点，概括它们的公共上位概念或共性。"
    "概括出的概念必须有语义内涵、可独立成义，"
    "禁止空洞聚合标签（如「信息碎片集合」「综合信息枢纽」）。"
    "如果这些节点并无真正的共性，据实说明而非硬凑。"
    "直接给出概括结论，简明扼要。"
)

USER_TEMPLATE = (
    "待概括节点:\n{material}\n\n"
    "聚焦语境:\n{focus}\n\n"
    "请概括这些节点的公共上位概念或共性。"
)


def parse(raw: str) -> str:
    """解析为概括结论文本（strip 自由文本）。

    非字符串或空白响应视为解析失败（空白概括无意义）→ 抛 ``LLMParseError``。
    """
    if not isinstance(raw, str):
        raise LLMParseError("generalize", str(raw), "expected string response")
    text = raw.strip()
    if not text:
        raise LLMParseError("generalize", raw, "empty response")
    return text

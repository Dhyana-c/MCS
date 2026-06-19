"""purpose='gen_graph_summary' 的 Prompt 包。

用于 GraphSummaryPlugin 压缩插件。输入：记忆图顶层组织中心（hub）的名称与内容
（经框架 ``ContextRenderer`` 渲染为 ``{material}``）。输出：整张图的主题摘要字符串，
受 ``max_tokens`` 限制（通过 free_args 传入）。

与节点级 ``gen_summary``（单节点摘要）的区别：本 purpose 把多个 hub 归纳为**图级**
主题描述，供记忆 agent 注入对话 system prompt 作为背景。
"""

from __future__ import annotations

from mcs.core.errors import LLMParseError

SYSTEM_PROMPT = (
    "你为一张记忆图生成整体主题摘要。输入是该图顶层组织中心（hub）的名称与内容。"
    "请归纳这张记忆图大概是关于什么、覆盖哪些主题领域、服务于什么目的，写成一段连贯文字。"
    "不要列表化、不要序号、不要空洞的聚合标签（如「综合信息枢纽」「信息碎片集合」）。"
)

USER_TEMPLATE = (
    "顶层组织中心:\n{material}\n\n"
    "用 {max_tokens} 字以内归纳这张记忆图的整体主题，直接输出摘要文本。"
)


def parse(raw: str) -> str:
    if not isinstance(raw, str):
        raise LLMParseError("gen_graph_summary", str(raw), "expected string response")
    return raw.strip()

"""purpose='merge_content' 的 Prompt 包。

合并两段 content 成**一个稳定、自包含的定义**（去重 + 择优 + 守时间归属）。供
`mcs.core.content_merge.merge_content` helper 在 write path `_dispatch_merge` 同名 /
同义对齐时调用（仅非子串 content 才调）。

时间归属按节点类型分流（unified-graph-schema 时间归属不变量）：概念零时间；
事实禁相对/单次时间、**保留**固定历史时间。模板携带 ``node_class``（概念 / 事实），
调用方（`WritePipeline._merge_content_llm`）必须传——`_safe_format` 遇缺占位符会
整体不格式化，target/incoming 会一并丢失。

与 ``merge``（agent 手动合并工具）不同：``merge`` 判若干节点是否同义 + 出整套方案
（keep/absorb/merged_content/aliases）；本 purpose **已知要合并**，只把两段 content
合成一段稳定定义。

输出纯文本（非 JSON），``parse`` 直接 strip 返回。
"""

from __future__ import annotations

from mcs.core.errors import LLMParseError

SYSTEM_PROMPT = (
    "你是知识图谱重构助手。给定一个节点的**两段 content 描述**（来自同名 / 同义节点的两次抽取），"
    "把它们合并成**一个稳定、自包含的定义**。"
    "\n\n合并原则："
    "\n- 去重：两段共有的信息只保留一份。"
    "\n- 择优：选更准确、更完整的表述；冲突时取更具体、更稳定的。"
    "\n- 不拼接：MUST NOT 把两段直接换行拼接，MUST 合成一段自然、连贯的定义。"
    "\n- 守时间归属（按节点类型）："
    "\n  - 节点类型为「概念」：content 零时间——MUST NOT 含任何时间词，"
    "既不含「今天/昨天/这次/未完成/计划中/将进行」等相对/单次时间，"
    "也不含「1976 年」等固定历史时间（带时间属性归事实命题，不进概念 content）。"
    "\n  - 节点类型为「事实」：MUST NOT 含相对/单次时间词（今天/这次/未完成/计划中等）；"
    "MUST 保留「1976 年/3 月 15 日」等固定历史时间——它是命题固有属性，不得丢弃。"
    "\n- 精简：控制在 ~24 token（英文约 100 字符，中文约 50 字）。"
    "\n\n**语言跟随**：合并后的 content MUST 沿用 target / incoming 的原文语言（同义节点本就同语种），"
    "MUST NOT 在合并时改换语言。"
    "\n\n只返回合并后的 content 纯文本，不要 JSON、不要解释、不要引号包裹。"
)

USER_TEMPLATE = (
    "节点类型：{node_class}\n\n"
    "content A:\n{target}\n\n"
    "content B:\n{incoming}\n\n"
    "请合并成一段稳定、自包含的定义（去重择优、不拼接、按上述节点类型守时间归属、~24 token）。"
)


def parse(raw: str) -> str:
    """返回合并后的 content 字符串（strip）。

    merge_content 输出纯文本（非 JSON），直接 strip 返回。空输出抛 LLMParseError
    让 helper 降级（保留 target）。容错剥一层首尾引号 / 反引号包裹。
    """
    text = (raw or "").strip()
    if not text:
        raise LLMParseError("merge_content", raw, "empty merged content")
    # 容错：LLM 偶尔回带一层引号 / 反引号包裹，剥掉。剥到空说明 LLM 只回了引号
    # 本身（如 '""'）—— 视为空输出降级（保留 target），不把引号字面量当 content。
    if len(text) >= 2 and text[0] == text[-1] and text[0] in ('"', "'", "`"):
        stripped = text[1:-1].strip()
        if not stripped:
            raise LLMParseError(
                "merge_content", raw, "quoted-but-empty merged content"
            )
        text = stripped
    return text

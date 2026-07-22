"""prompt 包共享辅助（不进 ``__init__.py`` import 清单——避免被 DEFAULT_PROMPTS 注册误扫）。

- ``NODE_CLASS_BY_LABEL``：node_class 枚举英中映射（prompt 协议层 concept/fact ↔ 中文常量）。
  原 ``extract_concepts`` / ``judge_relations`` 各内联一份，合一去重（migration-audit-fixes F2）。
- ``language_follow_clause``：统一「MUST 跟随原文语言、MUST NOT 翻译」骨架（prompt 包层，
  区别于 ``mcs_agent.loop.LANGUAGE_FOLLOW_PROMPT`` 的 agent 回答侧）。
"""

from __future__ import annotations

from mcs.entities.graph import CLASS_CONCEPT, CLASS_FACT

# node_class 枚举英中映射：prompt 协议层对 LLM 暴露英文 concept/fact（降低中文翻译诱导，
# 见 change prompt-language-following），parse 统一映射回中文常量；同时接受中文值
# （向后兼容旧 LLM 输出 / 旧库）。**存储层 node.node_class 取值不变（仍中文常量）**。
NODE_CLASS_BY_LABEL: dict[str, str] = {
    "concept": CLASS_CONCEPT,
    "fact": CLASS_FACT,
    CLASS_CONCEPT: CLASS_CONCEPT,
    CLASS_FACT: CLASS_FACT,
}


def language_follow_clause(subject: str, *, extra: str = "") -> str:
    """统一「MUST 跟随原文语言、MUST NOT 翻译」骨架（prompt 包层共享）。

    Args:
        subject: 该 prompt 的生成字段名（如 ``"name / content"``、``"theme / summary"``）。
        extra: 独特约束尾句（如别名的「MUST NOT 跨语言对译」）；空则省略。

    Returns:
        以 ``\\n\\n**语言跟随**（关键）：`` 开头的指令段，可直接拼到 ``SYSTEM_PROMPT`` 末尾。

    与 ``mcs_agent.loop.LANGUAGE_FOLLOW_PROMPT``（agent 回答侧、跟随**用户消息**语言）
    区分：本函数是 prompt 包层、跟随**输入文本 / 被处理节点**的原文语言。

    适用：跟随输入原文语言的生成型 prompt（extract_concepts / decide_hub / gen_summary 等）。
    **不适用**于 source 不同的 prompt（gen_graph_summary 跟随图内多数节点语言、synthesize /
    adjudicate 跟随查询语言）——那些保留各自手写段，避免骨架套用致 semantic drift。
    """
    clause = (
        f"\n\n**语言跟随**（关键）：{subject} MUST 跟随输入原文语言"
        "（中文输入写中文、英文输入写英文），MUST NOT 翻译——即使该实体在通用知识里有其他语言"
        "（如中文）的名称（如 Apple 不要写成「苹果公司」、Tesla 不要写成「特斯拉」），"
        "也 MUST 保留原文语言表述；混合语言文本逐实体保留其原文语言。"
    )
    if extra:
        clause += extra
    return clause

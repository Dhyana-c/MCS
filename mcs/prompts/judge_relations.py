"""purpose='judge_relations' 的 Prompt 包。

写入管线阶段 ④。输入：ConceptDraft 列表 + 已相关节点。
输出：DecisionList（操作记录列表，不是图变更）。
"""

from __future__ import annotations

import json

from mcs.core.decisions import ConceptDraft, Decision
from mcs.core.errors import LLMParseError
from mcs.utils.text_utils import strip_json_fence

SYSTEM_PROMPT = (
    "你是知识图谱关系判定助手。对每个新概念，结合「已知相关节点」判断:"
    "(a) merge 并入某已有节点; (b) create 新建并连边到锚点; "
    "(c) attach_statement 把关系说法挂到属性节点; (d) no_op 不入图。"
    "宁可不合，不可错合——把握不大就 create。"
)

USER_TEMPLATE = (
    "已知相关节点（含 id 与名称）:\n"
    "{material}\n\n"
    "待判定的新概念列表:\n"
    "{concepts}\n\n"
    "请输出 JSON 数组，每项形如:\n"
    '  {{"action": "merge|create|attach_statement|no_op",\n'
    '   "concept_name": "...",\n'
    '   "target_id": "<相关节点id>",\n'
    '   "edges_to": ["<锚点id>"],\n'
    '   "initial_statements": ["..."],\n'
    '   "statement": "...",\n'
    '   "aliases_to_add": ["..."],\n'
    '   "reason": "..."}}\n'
    "字段按 action 类型按需填写; 只返回 JSON。"
)


def parse(raw: str) -> list[Decision]:
    """将 LLM 响应解析为 DecisionList。

    LLM 返回的 ``concept_name`` 指向输入 ConceptDraft 的名称；
    调用方（写入管线 ④）负责将匹配的 ConceptDraft 对象重新挂回每个 Decision。
"""
    try:
        data = json.loads(strip_json_fence(raw))
    except json.JSONDecodeError as e:
        raise LLMParseError("judge_relations", raw, str(e)) from e
    if not isinstance(data, list):
        raise LLMParseError("judge_relations", raw, "expected JSON array")
    decisions: list[Decision] = []
    valid_actions = {"merge", "create", "attach_statement", "no_op"}
    for item in data:
        if not isinstance(item, dict) or "action" not in item:
            raise LLMParseError("judge_relations", raw, f"invalid item: {item!r}")
        action = item["action"]
        if action not in valid_actions:
            raise LLMParseError(
                "judge_relations", raw, f"unknown action: {action!r}"
            )
        decisions.append(
            Decision(
                action=action,
                concept=ConceptDraft(
                    name=item.get("concept_name", ""),
                    content="",  # will be re-attached by caller
                ),
                target_id=item.get("target_id"),
                edges_to=item.get("edges_to", []) or [],
                initial_statements=item.get("initial_statements", []) or [],
                statement=item.get("statement"),
                aliases_to_add=item.get("aliases_to_add", []) or [],
                reason=item.get("reason"),
            )
        )
    return decisions

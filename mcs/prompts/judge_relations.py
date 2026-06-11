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
    "(c) no_op 不入图。"
    "宁可不合，不可错合——把握不大就 create。"
    "此外，新概念彼此之间若有直接关系，用 edges_to_names 列出与它直接相关的"
    "**其它新概念名**（仅限本次待判定列表中的名称），以建立篇内连接。"
)

USER_TEMPLATE = (
    "已知相关节点（含 id 与名称）:\n"
    "{material}\n\n"
    "待判定的新概念列表:\n"
    "{concepts}\n\n"
    "请输出 JSON 数组，每项形如:\n"
    '  {{"action": "merge|create|no_op",\n'
    '   "concept_name": "...",\n'
    '   "target_id": "<相关节点id>",\n'
    '   "edges_to": ["<已存在锚点节点id>"],\n'
    '   "edges_to_names": ["<与之直接相关的其它新概念名>"],\n'
    '   "reason": "..."}}\n'
    "字段按 action 类型按需填写; edges_to 用已存在节点的 id，"
    "edges_to_names 用本次新概念的名称; 只返回 JSON。"
)


def parse(raw: str) -> list[Decision]:
    """将 LLM 响应解析为 DecisionList（宽容模式）。

    LLM 返回的 ``concept_name`` 指向输入 ConceptDraft 的名称；
    调用方（写入管线 ④）负责将匹配的 ConceptDraft 对象重新挂回每个 Decision。
"""
    from mcs.utils.text_utils import extract_json

    json_str = extract_json(raw)
    if not json_str:
        raise LLMParseError("judge_relations", raw, "no JSON found in response")

    try:
        data = json.loads(json_str)
    except json.JSONDecodeError as e:
        raise LLMParseError("judge_relations", raw, str(e)) from e

    if isinstance(data, dict):
        # 容忍 {"decisions": [...]} 包装或单个决策
        if "action" in data:
            data = [data]
        elif "decisions" in data and isinstance(data["decisions"], list):
            data = data["decisions"]
        elif "results" in data and isinstance(data["results"], list):
            data = data["results"]

    if not isinstance(data, list):
        raise LLMParseError(
            "judge_relations", raw, "expected JSON array or object"
        )
    decisions: list[Decision] = []
    valid_actions = {"merge", "create", "attach_statement", "no_op"}
    for item in data:
        if not isinstance(item, dict):
            continue
        action = item.get("action", "no_op")
        if action not in valid_actions:
            action = "no_op"  # 容忍无效 action
        decisions.append(
            Decision(
                action=action,
                concept=ConceptDraft(
                    name=item.get("concept_name", "") or item.get("name", ""),
                    content="",  # will be re-attached by caller
                ),
                target_id=item.get("target_id"),
                edges_to=item.get("edges_to", []) or [],
                edges_to_names=(
                    item.get("edges_to_names", [])
                    or item.get("related_concepts", [])
                    or item.get("edges_to_concepts", [])
                    or []
                ),
                initial_statements=item.get("initial_statements", []) or [],
                statement=item.get("statement"),
                aliases_to_add=item.get("aliases_to_add", []) or [],
                reason=item.get("reason"),
            )
        )
    return decisions

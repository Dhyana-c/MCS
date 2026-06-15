"""purpose='judge_relations' 的 Prompt 包（attribute_node 模式）。

attribute_node 模式下，阶段 ④ **不**为关系产出 label，而是产出"建属性节点 + 连无类型
关联边（``kind="assoc"``）"的决策意图（``create_attribute``）。概念本身仍走
merge / create / no_op。端点解析沿用 id / 同批 name 双轨（**无 label**）。

经 ``MCSConfig.prompt_overrides["judge_relations"]`` 在 ``knowledge_graph(
relation_model="attribute_node")`` 预设时注入。
"""

from __future__ import annotations

import json
import logging

from mcs.core.decisions import ConceptDraft, Decision
from mcs.core.errors import LLMParseError
from mcs.utils.text_utils import salvage_json_array

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "你是知识图谱关系判定助手（attribute_node 模式：关系具体化为属性节点 + 无类型关联边）。\n"
    "对每个新概念，结合「已知相关节点」判断: (a) merge 并入某已有节点; "
    "(b) create 新建概念节点; (c) no_op 不入图。"
    "宁可不合，不可错合——把握不大就 create。"
    "merge 时如果该概念有同义词、缩写、变体写法，在 aliases_to_add 中列出。"
    "\n\n【关系表示——本模式特有】关系**不**用带 label 的边表达，而是**具体化为属性节点**："
    "为每条关系（概念-概念，或概念-属性值）建一个属性节点（attr_name 为短名、"
    "attr_content 为**单一简短**的自然语言说法，如\"小明喜欢苹果\"），并用无类型关联边"
    "把它连到所涉及的每个概念端点。"
    "\n- 概念-概念关系（A 与 B 有关系）：建属性节点 R，endpoints 含 A 与 B（各一个端点）。"
    "\n- 概念-字面值（A 的某属性=某值，且值不值得单建节点）：建属性节点 R，attr_content "
    "内含该值，endpoints 只含 A（值不单列端点）。"
    "\n- attr_content 必须简短（一个说法 / 一句话），MUST NOT 写成段落。"
    "\n- endpoints：端点若是「已知相关节点」用 target_id；若是本批新概念用 target_name。"
    "\n- **不要**产出 label 字段，也**不要**用 edges_to / edges_to_names。"
    "\n- 若两概念之间没有实质关系，就**不要**为它们建属性节点（开放世界：缺边即未知）。"
)

USER_TEMPLATE = (
    "已知相关节点（含 id 与名称）:\n"
    "{material}\n\n"
    "待判定的新概念列表:\n"
    "{concepts}\n\n"
    "请输出 JSON 数组，每项为以下之一：\n"
    "概念判定：\n"
    '  {{"action": "merge|create|no_op", "concept_name": "...", '
    '"target_id": "<相关节点id>", "aliases_to_add": ["<同义词/变体>"], "reason": "..."}}\n'
    "关系具体化（为一条关系建属性节点 + 无类型关联边，**无 label**）：\n"
    '  {{"action": "create_attribute", "attr_name": "<短名>", '
    '"attr_content": "<单一简短说法>", "endpoints": ['
    '{{"target_id": "<已有节点id>"}} 或 {{"target_name": "<本批新概念名>"}}]}}\n'
    "概念判定与关系具体化可混合在同一数组中；字段按 action 类型按需填写。只返回 JSON。"
)


def parse(raw: str) -> list[Decision]:
    """将 LLM 响应解析为 DecisionList（attribute_node 模式，宽容模式）。

    ``create_attribute`` 项解析为属性节点决策（attr_name/attr_content + 端点双轨，
    无 label）；merge/create/no_op 项沿用概念结构（**不**解析 edges_to——本模式关系
    一律经 create_attribute，概念创建不带 fact 边）。
    """
    from mcs.utils.text_utils import extract_json

    json_str = extract_json(raw)
    if not json_str:
        raise LLMParseError("judge_relations_attr", raw, "no JSON found in response")

    try:
        data = json.loads(json_str)
    except json.JSONDecodeError as e:
        salvaged = salvage_json_array(json_str)
        if salvaged:
            logger.warning(
                "judge_relations_attr JSON 截断/格式坏，salvage 出 %d 个完整对象（%s）",
                len(salvaged), e,
            )
            data = salvaged
        else:
            raise LLMParseError("judge_relations_attr", raw, str(e)) from e

    if isinstance(data, dict):
        if "action" in data:
            data = [data]
        elif "decisions" in data and isinstance(data["decisions"], list):
            data = data["decisions"]
        elif "results" in data and isinstance(data["results"], list):
            data = data["results"]

    if not isinstance(data, list):
        raise LLMParseError(
            "judge_relations_attr", raw, "expected JSON array or object"
        )

    decisions: list[Decision] = []
    valid_actions = {"merge", "create", "create_attribute", "attach_statement", "no_op"}
    for item in data:
        if not isinstance(item, dict):
            continue
        action = item.get("action", "no_op")
        if action not in valid_actions:
            action = "no_op"

        if action == "create_attribute":
            assoc_to, assoc_to_names = _normalize_endpoints(
                item.get("endpoints")
                or item.get("assoc_to")
                or item.get("endpoints_to")
                or []
            )
            attr_content = (
                item.get("attr_content")
                or item.get("content")
                or item.get("statement")
                or ""
            )
            attr_name = item.get("attr_name") or item.get("name")
            if not attr_name:
                attr_name = _derive_attr_name(attr_content)
            decisions.append(
                Decision(
                    action="create_attribute",
                    attr_name=attr_name,
                    attr_content=attr_content,
                    assoc_to=assoc_to,
                    assoc_to_names=assoc_to_names,
                    reason=item.get("reason"),
                )
            )
        else:
            # 概念判定（merge/create/no_op/attach_statement）：本模式关系不经 edges_to，
            # 故不解析 edges_to / edges_to_names（保持空），关系一律走 create_attribute。
            decisions.append(
                Decision(
                    action=action,
                    concept=ConceptDraft(
                        name=item.get("concept_name", "") or item.get("name", ""),
                        content="",  # 由调用方重新挂回完整 ConceptDraft
                    ),
                    target_id=item.get("target_id"),
                    aliases_to_add=item.get("aliases_to_add", []) or [],
                    reason=item.get("reason"),
                )
            )
    return decisions


def _normalize_endpoints(raw: list) -> tuple[list[dict], list[dict]]:
    """把 endpoints 规范化为 (assoc_to, assoc_to_names)：id 轨与 name 轨分离，无 label。"""
    assoc_to: list[dict] = []
    assoc_to_names: list[dict] = []
    for item in raw or []:
        if isinstance(item, str):
            # 纯字符串端点：无法区分 id/name，按名解析兜底
            if item:
                assoc_to_names.append({"target_name": item})
            continue
        if not isinstance(item, dict):
            continue
        tid = item.get("target_id") or item.get("id")
        tname = item.get("target_name") or item.get("name")
        if tid:
            assoc_to.append({"target_id": tid})
        elif tname:
            assoc_to_names.append({"target_name": tname})
    return assoc_to, assoc_to_names


def _derive_attr_name(content: str, max_len: int = 40) -> str:
    """从 attr_content 派生属性节点短名（取首行前若干字符）。"""
    lines = (content or "").strip().splitlines()
    s = lines[0] if lines else ""
    return s[:max_len] or "attribute"

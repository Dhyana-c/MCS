"""purpose='judge_relations' 的 Prompt 包。

写入管线阶段 ④。输入：ConceptDraft 列表 + 已相关节点。
输出：DecisionList（操作记录列表，不是图变更）。

edges_to / edges_to_names 为 list[dict]，每项含 target_id/target_name。
统一模型下这些边为 ``关联`` 边（无 label、无 kind；谓词落事实节点 content）。
一条关系 = 一个方向，不自动镜像反向。

互斥边（``互斥``）由 ``mutex_with`` / ``mutex_with_names`` 字段表达，
仅适用于事实 ↔ 事实。
"""

from __future__ import annotations

import json
import logging

from mcs.core.errors import LLMParseError
from mcs.entities.decisions import ConceptDraft, Decision
from mcs.entities.graph import CLASS_CONCEPT, CLASS_FACT
from mcs.utils.text_utils import salvage_json_array, strip_json_fence

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "你是知识图谱关系判定助手。对每个新概念/事实，结合「已知相关节点」判断:"
    "(a) merge 并入某已有节点; (b) create 新建并连边到锚点; "
    "(c) no_op 不入图。"
    "宁可不合，不可错合——把握不大就 create。"
    "merge 时如果该概念有同义词、缩写、变体写法，在 aliases_to_add 中列出。"
    "\n\n若一个概念与某个外部实体（已知节点或本批新概念）存在实质关系"
    "（如「创立」「属于」「包含」「影响」），用 edges_to（已知节点 id）或 "
    "edges_to_names（本批新概念名）连一条边。"
    "\n\n若两个概念之间没有实质关系，就**不要**在 edges_to / edges_to_names 中列出"
    "（开放世界：缺边即代表未知，无需显式表达「无关系」）。"
    "\n\n对每个待判定项，判断其 node_class："
    "「概念」=名词性实体（人/组织/地点/术语/抽象概念）；"
    "「事实」=含谓词的命题陈述（关系陈述、属性陈述）。"
    "\n\n若某个事实与已有事实相互排斥（如两个矛盾说法），在 mutex_with 中填入已有事实节点 id。"
    "若同一批新概念中有互斥事实，在 mutex_with_names 中填入对方概念名。"
    "互斥仅适用于事实↔事实，概念之间不判互斥。"
)

USER_TEMPLATE = (
    "已知相关节点（含 id 与名称）:\n"
    "{material}\n\n"
    "待判定的新概念列表:\n"
    "{concepts}\n\n"
    "请输出 JSON 数组，每项形如:\n"
    '  {{"action": "merge|create|no_op",\n'
    '   "concept_name": "...",\n'
    '   "node_class": "概念|事实",\n'
    '   "target_id": "<相关节点id>",\n'
    '   "aliases_to_add": ["<同义词/缩写/变体写法>"],\n'
    '   "edges_to": [{{"target_id": "<锚点id>"}}],\n'
    '   "edges_to_names": [{{"target_name": "<其它新概念名>"}}],\n'
    '   "mutex_with": ["<已有事实节点id>"],\n'
    '   "mutex_with_names": ["<同批新事实名>"],\n'
    '   "reason": "..."}}\n'
    "字段按 action 类型按需填写; edges_to 用已存在节点的 id，"
    "edges_to_names 用本次新概念的名称; aliases_to_add 仅 merge 时填写;"
    "mutex_with / mutex_with_names 仅事实间互斥时填写;"
    "只返回 JSON。"
)


def parse(raw: str) -> list[Decision]:
    """将 LLM 响应解析为 DecisionList（宽容模式）。

    LLM 返回的 ``concept_name`` 指向输入 ConceptDraft 的名称；
    调用方（写入管线 ④）负责将匹配的 ConceptDraft 对象重新挂回每个 Decision。

    edges_to / edges_to_names 支持两种格式：
    - 新格式：list[dict] with target_id/target_name
    - 旧格式：list[str]（纯 id/名称）
    """
    from mcs.utils.text_utils import extract_json

    json_str = extract_json(raw)
    if not json_str:
        raise LLMParseError("judge_relations", raw, "no JSON found in response")

    try:
        data = json.loads(json_str)
    except json.JSONDecodeError as e:
        # deepseek 对概念多的文档偶尔吐超长 JSON、中途截断 → 整段 loads 失败。
        # 逐个 salvage 出完整对象，救回该文档大部分关系，而非整篇丢弃。
        salvaged = salvage_json_array(json_str)
        if salvaged:
            logger.warning(
                "judge_relations JSON 截断/格式坏，salvage 出 %d 个完整对象（%s）",
                len(salvaged), e,
            )
            data = salvaged
        else:
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
    valid_actions = {"merge", "create", "no_op"}
    for item in data:
        if not isinstance(item, dict):
            continue
        action = item.get("action", "no_op")
        if action not in valid_actions:
            # 容忍无效 action（含已废弃的 attach_statement / create_attribute）
            action = "no_op"
        # node_class：仅接受"概念"和"事实"，其余回退为"概念"
        raw_nc = str(item.get("node_class", CLASS_CONCEPT)).strip()
        node_class = raw_nc if raw_nc in (CLASS_CONCEPT, CLASS_FACT) else CLASS_CONCEPT
        # mutex_with：已有事实节点 id 列表
        raw_mutex = item.get("mutex_with", []) or []
        mutex_with = [str(x) for x in raw_mutex if isinstance(x, str) and x]
        # mutex_with_names：同批新事实名列表
        raw_mutex_names = item.get("mutex_with_names", []) or []
        mutex_with_names = [str(x) for x in raw_mutex_names if isinstance(x, str) and x]
        decisions.append(
            Decision(
                action=action,
                concept=ConceptDraft(
                    name=item.get("concept_name", "") or item.get("name", ""),
                    content="",  # will be re-attached by caller
                    node_class=node_class,
                ),
                target_id=item.get("target_id"),
                edges_to=_normalize_edges_to(item.get("edges_to", []) or []),
                edges_to_names=_normalize_edges_to_names(
                    item.get("edges_to_names", [])
                    or item.get("related_concepts", [])
                    or item.get("edges_to_concepts", [])
                    or []
                ),
                aliases_to_add=item.get("aliases_to_add", []) or [],
                reason=item.get("reason"),
                node_class=node_class,
                mutex_with=mutex_with,
                mutex_with_names=mutex_with_names,
            )
        )
    return decisions


def _normalize_edges_to(raw: list) -> list[dict]:
    """规范化为 list[dict]（每项仅含 target_id），兼容旧格式 list[str]、剥离残留 label。"""
    result = []
    for item in raw:
        if isinstance(item, dict):
            tid = item.get("target_id")
            if tid:
                result.append({"target_id": tid})
        elif isinstance(item, str):
            result.append({"target_id": item})
    return result


def _normalize_edges_to_names(raw: list) -> list[dict]:
    """规范化为 list[dict]（每项仅含 target_name），兼容旧格式 list[str]、剥离残留 label。"""
    result = []
    for item in raw:
        if isinstance(item, dict):
            tname = item.get("target_name")
            if tname:
                result.append({"target_name": tname})
        elif isinstance(item, str):
            result.append({"target_name": item})
    return result

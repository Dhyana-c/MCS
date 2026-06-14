"""purpose='judge_relations' 的 Prompt 包。

写入管线阶段 ④。输入：ConceptDraft 列表 + 已相关节点。
输出：DecisionList（操作记录列表，不是图变更）。

edges_to / edges_to_names 为 list[dict]，每项含 target_id/target_name + label。
一条关系 = 一个方向 + 一个 label，不自动镜像反向。
"""

from __future__ import annotations

import json
import logging

from mcs.core.decisions import ConceptDraft, Decision
from mcs.core.errors import LLMParseError
from mcs.utils.text_utils import strip_json_fence

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "你是知识图谱关系判定助手。对每个新概念，结合「已知相关节点」判断:"
    "(a) merge 并入某已有节点; (b) create 新建并连边到锚点; "
    "(c) no_op 不入图。"
    "宁可不合，不可错合——把握不大就 create。"
    "merge 时如果该概念有同义词、缩写、变体写法，在 aliases_to_add 中列出。"
    "\n\n属性升格规则：如果一个概念的 relation_hints 或 content 中包含指向外部实体"
    "的关系（如「创始人：张三」「属于：人工智能」），必须为该关系创建一条事实边——"
    "若外部实体已在已知节点中，用 edges_to 指向它；若是本批新概念，用 edges_to_names。"
    "\n\n每条关系必须附带一个粗粒度 label（如「创立」「属于」「包含」「影响」）。"
    "一条关系 = 一个方向 + 一个 label，不要自动生成反向关系。"
    "\n\n若两个概念之间没有实质关系，就**不要**在 edges_to / edges_to_names 中列出"
    "（开放世界：缺边即代表未知，无需显式表达「无关系」）。"
    "**禁止**用「无关 / 不相关 / 无 / unrelated」等否定词或空泛词充当 label。"
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
    '   "aliases_to_add": ["<同义词/缩写/变体写法>"],\n'
    '   "edges_to": [{{"target_id": "<锚点id>", "label": "<粗粒度谓词>"}}],\n'
    '   "edges_to_names": [{{"target_name": "<其它新概念名>", "label": "<粗粒度谓词>"}}],\n'
    '   "reason": "..."}}\n'
    "字段按 action 类型按需填写; edges_to 用已存在节点的 id + label，"
    "edges_to_names 用本次新概念的名称 + label; aliases_to_add 仅 merge 时填写;"
    "只返回 JSON。"
)


def parse(raw: str) -> list[Decision]:
    """将 LLM 响应解析为 DecisionList（宽容模式）。

    LLM 返回的 ``concept_name`` 指向输入 ConceptDraft 的名称；
    调用方（写入管线 ④）负责将匹配的 ConceptDraft 对象重新挂回每个 Decision。

    edges_to / edges_to_names 支持两种格式：
    - 新格式：list[dict] with target_id/target_name + label
    - 旧格式：list[str]（纯 id/名称），label 默认为 ""
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
        salvaged = _salvage_json_array(json_str)
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
                edges_to=_normalize_edges_to(item.get("edges_to", []) or []),
                edges_to_names=_normalize_edges_to_names(
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


def _salvage_json_array(s: str) -> list:
    """从（可能被截断 / 格式坏的）JSON 数组文本中尽量解析出**完整**的对象元素。

    deepseek 等模型对概念多的文档偶尔吐超长 JSON、中途命中输出上限被截断，
    导致整段 ``json.loads`` 失败、该文档关系整篇丢弃。此函数从 ``[`` 起逐个
    ``raw_decode`` 数组元素，遇到第一个坏 / 截断元素即停，保留之前的完整对象。
    """
    start = s.find("[")
    if start == -1:
        return []
    decoder = json.JSONDecoder()
    items: list = []
    i = start + 1
    n = len(s)
    while i < n:
        # 跳过元素间的空白与逗号
        while i < n and s[i] in " \t\r\n,":
            i += 1
        if i >= n or s[i] == "]":
            break
        try:
            obj, end = decoder.raw_decode(s, i)
        except json.JSONDecodeError:
            break  # 截断 / 格式坏从此处起 → 停，保留已解析的完整对象
        items.append(obj)
        i = end
    return items


# 无意义 / 否定型 label —— LLM 偶尔对**不相关**的概念也建边并标注「无关」，这类边
# 断言"无关系"本身就是非关系（开放世界下缺边即未知），应丢弃以免污染事实图。
_MEANINGLESS_LABELS = frozenset({
    "无关", "不相关", "无关系", "没有关系", "不相干", "无明显关系", "无",
    "unrelated", "irrelevant", "none", "n/a", "na", "no relation", "not related",
})


def _is_meaningless_label(label: str) -> bool:
    """label 归一化后落入否定 / 空泛词表则视为无意义（应丢弃该边）。"""
    return (label or "").strip().lower() in _MEANINGLESS_LABELS


def _normalize_edges_to(raw: list) -> list[dict]:
    """将 edges_to 规范化为 list[dict]，兼容旧格式 list[str]；丢弃无意义 label 的边。"""
    result = []
    for item in raw:
        if isinstance(item, dict):
            if _is_meaningless_label(item.get("label", "")):
                continue
            result.append(item)
        elif isinstance(item, str):
            result.append({"target_id": item, "label": ""})
    return result


def _normalize_edges_to_names(raw: list) -> list[dict]:
    """将 edges_to_names 规范化为 list[dict]，兼容旧格式 list[str]；丢弃无意义 label 的边。"""
    result = []
    for item in raw:
        if isinstance(item, dict):
            if _is_meaningless_label(item.get("label", "")):
                continue
            result.append(item)
        elif isinstance(item, str):
            result.append({"target_name": item, "label": ""})
    return result

"""purpose='extract_concepts' 的 Prompt 包。

写入管线阶段 ③。输入：原始文本 + 已相关节点（以便 LLM 复用已有名称）。
输出：List[ConceptDraft]。

content 遵循 lean 基线：仅含定义 + 短叶子属性（~24 token）。
关系语义不在 content 中——由 judge_relations 判定后写入事实边。
"""

from __future__ import annotations

import json
import logging

from mcs.core.errors import LLMParseError
from mcs.entities.decisions import ConceptDraft
from mcs.entities.graph import CLASS_CONCEPT, CLASS_FACT
from mcs.utils.text_utils import salvage_json_array, strip_json_fence

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "你是知识图谱构建助手。从输入文本中识别独立的概念和事实。"
    "如果某概念已存在于「已知相关概念」中，请复用其名称。"
    "\n\n对每个概念的 content，写 1-2 句精简自包含描述，仅包含：\n"
    "- 这个概念是什么（定义/身份）\n"
    "- 关键的叶子属性（数值、日期、地点等具体信息）\n\n"
    "以下内容不要写入 content，而是放在 relation_hints 里：\n"
    "- 与其他实体/概念的关系（谁做了什么、属于什么）\n"
    "- 对外部实体的引用（人名、组织名等——这些应作为独立概念提取）\n\n"
    "content 控制在 ~24 token（英文约 100 字符，中文约 50 字）以内。\n\n"
    "对每个识别项，判断它是「概念」还是「事实」：\n"
    "- 概念（node_class=\"概念\"）：名词性实体（人名、组织、地点、技术术语、抽象概念等）\n"
    "- 事实（node_class=\"事实\"）：含谓词的命题陈述（如「X 创立了 Y」「Z 位于 W」等关系陈述）\n"
    "事实的 content 应包含完整的谓词表述（如「创立了苹果公司」），端点概念单独提取为概念。"
)

USER_TEMPLATE = (
    "已知相关概念（可复用其名称）:\n"
    "{material}\n\n"
    "输入文本:\n"
    "{text}\n\n"
    '请输出 JSON 数组，每项形如 {{"name": "...", "content": "1-2句精简定义+叶子属性", '
    '"relation_hints": ["关系短语", ...], "node_class": "概念|事实"}}。'
    "content 只放定义和叶子属性，不放关系叙述；关系放 relation_hints。"
    "node_class 为「概念」或「事实」；名词性实体标「概念」，含谓词的命题陈述标「事实」。"
    "对文本中提到的外部实体（人名、组织名等），即使只在一个属性中出现，也作为独立概念提取。"
    "只返回 JSON，不要其他解释。"
)


def parse(raw: str) -> list[ConceptDraft]:
    """将 LLM 响应解析为 ConceptDraft 列表（宽容模式）。"""
    from mcs.utils.text_utils import extract_json

    json_str = extract_json(raw)
    if not json_str:
        raise LLMParseError("extract_concepts", raw, "no JSON found in response")

    try:
        data = json.loads(json_str)
    except json.JSONDecodeError as e:
        # 超长输出被截断 / 中途格式坏 → 逐个 salvage 出完整概念对象，
        # 避免整篇文档因一个坏对象而丢弃（与 judge_relations 同款兜底）。
        salvaged = salvage_json_array(json_str)
        if salvaged:
            logger.warning(
                "extract_concepts JSON 截断/格式坏，salvage 出 %d 个完整对象（%s）",
                len(salvaged), e,
            )
            data = salvaged
        else:
            raise LLMParseError("extract_concepts", raw, str(e)) from e

    if isinstance(data, dict):
        # 容忍单个概念对象或 {"concepts": [...]} 包装
        # 先检查常见的包装字段
        for key in ("concepts", "items", "results", "data"):
            if key in data and isinstance(data[key], list):
                data = data[key]
                break
        else:
            # 单个概念对象（不管字段名是什么）
            data = [data]

    if not isinstance(data, list):
        raise LLMParseError(
            "extract_concepts", raw, "expected JSON array or object"
        )

    result: list[ConceptDraft] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        name = item.get("name") or item.get("concept") or item.get("term") or item.get("entity")
        if not name:
            continue
        # node_class：仅接受"概念"和"事实"，其余回退为"概念"（向后兼容）
        raw_nc = str(item.get("node_class", CLASS_CONCEPT)).strip()
        node_class = raw_nc if raw_nc in (CLASS_CONCEPT, CLASS_FACT) else CLASS_CONCEPT
        result.append(
            ConceptDraft(
                name=str(name),
                content=item.get("content", "") or item.get("description", "") or "",
                relation_hints=item.get("relation_hints", []) or item.get("relations", []) or [],
                node_class=node_class,
            )
        )
    return result

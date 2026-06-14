"""purpose='extract_concepts' 的 Prompt 包。

写入管线阶段 ③。输入：原始文本 + 已相关节点（以便 LLM 复用已有名称）。
输出：List[ConceptDraft]。

content 遵循 lean 基线：仅含定义 + 短叶子属性（~24 token）。
关系语义不在 content 中——由 judge_relations 判定后写入事实边。
"""

from __future__ import annotations

import json

from mcs.core.decisions import ConceptDraft
from mcs.core.errors import LLMParseError
from mcs.utils.text_utils import strip_json_fence

SYSTEM_PROMPT = (
    "你是知识图谱构建助手。从输入文本中识别独立的概念。"
    "如果某概念已存在于「已知相关概念」中，请复用其名称。"
    "\n\n对每个概念的 content，写 1-2 句精简自包含描述，仅包含：\n"
    "- 这个概念是什么（定义/身份）\n"
    "- 关键的叶子属性（数值、日期、地点等具体信息）\n\n"
    "以下内容不要写入 content，而是放在 relation_hints 里：\n"
    "- 与其他实体/概念的关系（谁做了什么、属于什么）\n"
    "- 对外部实体的引用（人名、组织名等——这些应作为独立概念提取）\n\n"
    "content 控制在 ~24 token（英文约 100 字符，中文约 50 字）以内。"
)

USER_TEMPLATE = (
    "已知相关概念（可复用其名称）:\n"
    "{material}\n\n"
    "输入文本:\n"
    "{text}\n\n"
    '请输出 JSON 数组，每项形如 {{"name": "...", "content": "1-2句精简定义+叶子属性", "relation_hints": ["关系短语", ...]}}。'
    "content 只放定义和叶子属性，不放关系叙述；关系放 relation_hints。"
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
        result.append(
            ConceptDraft(
                name=str(name),
                content=item.get("content", "") or item.get("description", "") or "",
                relation_hints=item.get("relation_hints", []) or item.get("relations", []) or [],
            )
        )
    return result

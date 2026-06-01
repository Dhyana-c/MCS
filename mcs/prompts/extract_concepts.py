"""purpose='extract_concepts' 的 Prompt 包。

写入管线阶段 ③。输入：原始文本 + 已相关节点（以便 LLM 复用已有名称）。
输出：List[ConceptDraft]。
"""

from __future__ import annotations

import json

from mcs.core.decisions import ConceptDraft
from mcs.core.errors import LLMParseError
from mcs.utils.text_utils import strip_json_fence

SYSTEM_PROMPT = (
    "你是知识图谱构建助手。从输入文本中识别独立的概念，"
    "如果某概念已存在于「已知相关概念」中，请复用其名称。"
    "概念之间的关系用自然语言短语写在 relation_hints 里，不要做谓词归一。"
)

USER_TEMPLATE = (
    "已知相关概念（可复用其名称）:\n"
    "{material}\n\n"
    "输入文本:\n"
    "{text}\n\n"
    '请输出 JSON 数组，每项形如 {{"name": "...", "content": "...", "relation_hints": ["..."]}}。'
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

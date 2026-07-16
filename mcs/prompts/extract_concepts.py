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
    "- 关键的叶子属性（数值、地点等具体信息）\n\n"
    "以下内容不要写入 content，而是放在 relation_hints 里：\n"
    "- 与其他实体/概念的关系（谁做了什么、属于什么）\n"
    "- 对外部实体的引用（人名、组织名等——这些应作为独立概念提取）\n\n"
    "content 控制在 ~24 token（英文约 100 字符，中文约 50 字）以内。\n\n"
    "对每个识别项，判断它是「概念」还是「事实」：\n"
    "- 概念（node_class=\"概念\"）：名词性实体（人名、组织、地点、技术术语、抽象概念等）\n"
    "- 事实（node_class=\"事实\"）：含谓词的命题陈述（如「X 创立了 Y」「Z 位于 W」等关系陈述）\n"
    "事实的 content 应包含完整的谓词表述（如「创立了苹果公司」），端点概念单独提取为概念。\n\n"
    "**时间归属**（关键，必须遵守；判据 = 时间形态，非\"是否事件性\"）：\n"
    "- 概念 content MUST NOT 含任何时间词——既不含「今天/这次/未完成/计划中/将进行」等"
    "相对/单次时间，也不含「1976 年」等固定历史时间。带时间属性（如「创立于 1976」）"
    "归事实命题，MUST NOT 进概念 content；MUST NOT 把「日期」当概念的叶子属性。\n"
    "- 事实 content MUST NOT 含相对/单次时间词（今天/这次/未完成/计划中）；"
    "MAY 含固定历史时间（如「1976 年」「2023 年 1 月」）作命题属性。\n"
    "- **带固定历史时间的已完成世界发生**（如「2023 年 1 月 Google 裁员 12000 人」"
    "「某队 11 月 5 日击败对手」）→ 抽成**历史事实命题**（时间作属性留在事实 content），"
    "MUST NOT 因其\"事件性\"丢弃或概括。\n"
    "- **相对/单次时间的发生**（如「今天去按摩」「这次会议」）→ 抽成去时间化的事实"
    "（如「用户去按摩」），相对时间归事件层、MUST NOT 进事实 content。\n"
    "- 清单/汇总型内容（逐条列出的公司/比赛/交易等）MUST 逐条抽取——每条一个事实、"
    "涉及实体各自抽为概念，MUST NOT 卷成一个聚合概念。\n"
    "- MUST NOT 把偏好/模式（如「喜欢 X」）当概念/事实——偏好靠概念被多事件背书涌现；"
    "无时间锚的模糊事件指代（「X 的情况」）也不抽。\n"
)

USER_TEMPLATE = (
    "已知相关概念（可复用其名称）:\n"
    "{material}\n\n"
    "输入文本:\n"
    "{text}\n\n"
    '请输出 JSON 数组，每项形如 {{"name": "...", "content": "1-2句精简定义+叶子属性", '
    '"relation_hints": ["关系短语", ...], "node_class": "概念|事实"}}。'
    "content 只放定义和叶子属性，不放关系叙述（关系放 relation_hints）；"
    "**概念 content 零时间；事实禁相对/单次时间、允许固定历史时间**（如 1976、2023 年 1 月）；"
    "**带固定历史时间的已完成发生抽成历史事实**（如「2023 年 1 月 Google 裁员 12000 人」），"
    "相对时间的发生抽成去时间化事实（「今天去按摩」→「用户去按摩」）；"
    "清单/汇总内容逐条抽取（每条一个事实），不要概括成聚合概念。"
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
            # 任意键包装的数组（JSON 模式下模型可能自选包装键）：仅**单键 dict 且值
            # 为列表**才视为包装拆开——概念对象自身也带列表字段（relation_hints），
            # 多键 dict 必须按单个概念对象处理，不可误拆。
            only_val = next(iter(data.values())) if len(data) == 1 else None
            data = only_val if isinstance(only_val, list) else [data]

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

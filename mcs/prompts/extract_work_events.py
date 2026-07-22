"""purpose='extract_work_events' 的 Prompt 包。

写入管线阶段 ③b（仅 ``work_id`` 非空时启用）。输入：作品文本 + 作品名。
输出：List[WorkEventDraft]——作品文本中"带时间的叙述发生"（作品叙事事件）。

与 ``extract_concepts``（概念 / 事实）分工：本 purpose 只抽**发生**（谁在何时做了
什么），不抽静态设定 / 实体定义；纪年保留原文形态（"200 年" / "建安五年" / "2039"），
不换算、不编造。**唯一例外（锚点解析，work-event-anchor-resolution）**：文本自带显式
时间锚点且相对表述可确定到具体某天（锚点 8 May, 2023 + "yesterday"）→ narr_timestamp
MAY 解析为 ISO 日期（"2023-05-07"）；定不到某天仍保留原文。宪法铁律精确化：现实摄入
事件不经 LLM；作品叙事事件经 LLM 抽取。
"""

from __future__ import annotations

import json
import logging

from mcs.core.errors import LLMParseError
from mcs.entities.decisions import WorkEventDraft
from mcs.utils.text_utils import salvage_json_array

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "你是叙事分析助手。从作品《{work_id}》的文本中识别**带时间的叙述发生**"
    "（作品内的事件：谁在什么时间做了什么 / 发生了什么）。\n\n"
    "抽取规则：\n"
    "- 只抽**发生**（动作、事件、变故），不抽静态设定、人物介绍、实体定义、观点议论。\n"
    "- narr_timestamp 填**作品内的纪年 / 时间**，保留原文形态（如\"200 年\"、"
    "\"建安五年\"、\"2039\"、\"三日后\"）——不换算、不猜测；文本没写明确时间就填 null。\n"
    "- **锚点解析（上一条的唯一例外）**：文本自带**显式时间锚点**（如逐行的"
    "\"[1:56 pm on 8 May, 2023]\"标记），且发生时间是**相对锚点**的表述"
    "（yesterday / 昨天 / two days ago / 前天）→ 对锚点做日期算术，narr_timestamp 写"
    "**ISO 日期**（锚点 8 May, 2023 + \"yesterday\" → \"2023-05-07\"）。仅当能**确定"
    "到具体某天**才这样写；定不到具体某天（\"last week\" / \"last year\"，或需要知道"
    "锚点是星期几）→ 仍保留原文形态，不要编日期、不要写 \"2023-05\" 这类残缺形态。"
    "无锚点时本例外不适用。\n"
    "- MUST NOT 使用现实世界的当前时间；作品时间轴与现实时间轴相互独立。\n"
    "- participants 填该发生的**参与者名字**（人物 / 组织，用文本中的称呼），没有则空数组。\n"
    "- content 用 1-2 句转述该发生（含关键结果），name 为简短事件名（如\"曹操杀吕伯奢\"）。\n"
    "- 宁缺毋滥：不确定是不是\"发生\"就不抽；一段文本通常只有 0-5 个值得记的叙述发生。"
    "\n\n**语言跟随**：name / content / participants MUST 跟随作品原文语言（中文作品写中文、"
    "英文作品写英文、文言作品保留文言表述），MUST NOT 翻译为其他语言、MUST NOT 用现代汉语"
    "转译文言原文；narr_timestamp 保留原文形态不变。"
)

USER_TEMPLATE = (
    "作品：{work_id}\n\n"
    "作品文本：\n{text}\n\n"
    '请输出 JSON 数组，每项形如 {{"name": "简短事件名", "content": "1-2句发生转述", '
    '"narr_timestamp": "作品纪年（原文形态）或 null", "participants": ["参与者名", ...]}}。\n'
    "只抽带叙述发生的事件（0-5 个），没有则返回 []。只返回 JSON，不要其他解释。"
)


def parse(raw: str) -> list[WorkEventDraft]:
    """将 LLM 响应解析为 WorkEventDraft 列表（宽容模式，同 extract_concepts 口径）。"""
    from mcs.utils.text_utils import extract_json

    json_str = extract_json(raw)
    if not json_str:
        raise LLMParseError("extract_work_events", raw, "no JSON found in response")

    try:
        data = json.loads(json_str)
    except json.JSONDecodeError as e:
        # 超长输出被截断 / 中途格式坏 → 逐个 salvage 出完整对象（同 extract_concepts 兜底）
        salvaged = salvage_json_array(json_str)
        if salvaged:
            logger.warning(
                "extract_work_events JSON 截断/格式坏，salvage 出 %d 个完整对象（%s）",
                len(salvaged), e,
            )
            data = salvaged
        else:
            raise LLMParseError("extract_work_events", raw, str(e)) from e

    if isinstance(data, dict):
        for key in ("events", "items", "results", "data"):
            if key in data and isinstance(data[key], list):
                data = data[key]
                break
        else:
            # 任意键包装的数组（JSON 模式下模型可能自选包装键）：仅单键 dict 且值为
            # 列表才视为包装（事件对象自身带 participants 列表，多键不可误拆）。
            only_val = next(iter(data.values())) if len(data) == 1 else None
            data = only_val if isinstance(only_val, list) else [data]

    if not isinstance(data, list):
        raise LLMParseError(
            "extract_work_events", raw, "expected JSON array or object"
        )

    result: list[WorkEventDraft] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        name = item.get("name") or item.get("event") or ""
        if not name:
            continue
        ts = item.get("narr_timestamp") or item.get("timestamp") or None
        participants = item.get("participants") or []
        if not isinstance(participants, list):
            participants = []
        result.append(
            WorkEventDraft(
                name=str(name),
                content=str(item.get("content", "") or ""),
                narr_timestamp=(str(ts) if ts else None),
                participants=[str(p) for p in participants if p],
            )
        )
    return result

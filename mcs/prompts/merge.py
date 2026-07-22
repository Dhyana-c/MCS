"""purpose='merge' 的 Prompt 包。

记忆 agent 的 ``merge`` 工具（概念合并·写图）：给定若干节点，让 LLM 判断它们是否
**本就同一个**（异名 / 同义 / 重复建），若是则产出合并方案（``keep`` 保留、``absorb``
吸收删除、``merged_content``、``aliases_to_add``），供 ``MemoryStore.merge_concepts`` 执行。
非同义或互斥时返回 ``action=noop``、不执行。

**互斥禁合**：``keep`` 与任一 ``absorb`` 间若有 ``互斥`` 边，合并会塌缩矛盾——MUST
返回 noop。``MemoryStore._do_merge`` 另有机制层保险（执行前扫互斥边）。

**不复用 ``judge_relations``**：其 merge 是写入期对齐（对每个新概念判 merge/create/no_op
对齐到已有节点），口径与 agent 手动合并不同。

本 prompt 只产方案、不改图；执行 + 守门 + 原子事务由 ``MemoryStore.merge_concepts`` 负责。
``parse`` 只做结构校验；**keep/absorb 是否在传入 id 集合内**的校验在 ``_do_merge`` 做。
"""

from __future__ import annotations

import json

from mcs.core.errors import LLMParseError
from mcs.utils.text_utils import extract_json

SYSTEM_PROMPT = (
    "你是知识图谱重构助手。判断给定的【若干概念节点】是否**本就同一个**（异名 / "
    "同义 / 重复建）——若是，给出合并方案；若否，明确返回 noop。"
    "\n\n合并时产出：keep（保留节点的 id）、absorb（被吸收删除的节点 id 列表）、"
    "merged_content（合并后的 content，可空则用 keep 的）、aliases_to_add（异名收口，"
    "把 absorb 的 name / 别名并进 keep）。"
    "\n\n硬约束："
    "\n- **互斥禁合**：keep 与任一 absorb 之间若有互斥关系（事实↔事实互斥），MUST 返回"
    " action=noop 并在 reason 说明——合并互斥会塌缩矛盾。"
    "\n- 同名 ≠ 同义：'苹果'水果 vs '苹果'公司是不同实体，MUST 返回 noop（这是消歧，"
    "不是合并）。"
    "\n- 两个 merely 相关的概念（如'小明'与'同事'）MUST NOT 合并——关联用关联边表达。"
    "\n- 拿不准是否同一个——默认 noop（错合丢失身份、断掉背书 / 互斥，比不合糟）。"
    "\n\n**语言跟随**：merged_content MUST 沿用 keep / absorb 节点的原文语言（同义节点本就同语种），"
    "MUST NOT 翻译；aliases_to_add MUST 是该节点原语言下的异名 / 变体写法，MUST NOT 给跨语言对译。"
    "\n\n只返回 JSON，不要解释。"
)

USER_TEMPLATE = (
    "待判定的节点（含 id、name、content）:\n{material}\n\n"
    "聚焦语境:\n{focus}\n\n"
    "请判断这些节点是否本就同一个。返回 JSON：\n"
    '{{"action": "merge|noop",\n'
    ' "keep": "<保留节点 id>",\n'
    ' "absorb": ["<被吸收节点 id>", ...],\n'
    ' "merged_content": "合并后 content（可空）",\n'
    ' "aliases_to_add": ["<异名>", ...],\n'
    ' "reason": "..."}}\n'
    "action=noop 时仅需 reason。merge 时 keep 不在 absorb 中。"
)


def parse(raw: str) -> dict:
    """解析 merge purpose 的 LLM 输出为结构化方案 dict。

    返回 ``{"action": "merge"|"noop", "keep": ..., "absorb": [...],
    "merged_content": ..., "aliases_to_add": [...], "reason": ...}``。
    **只做结构校验**；keep/absorb 是否在传入 id 集合内、keep 是否互斥 absorb 的校验
    在 ``MemoryStore._do_merge``（那里才有传入集合与图状态）。
    """
    json_str = extract_json(raw)
    if not json_str:
        raise LLMParseError("merge", raw, "no JSON found in response")
    try:
        data = json.loads(json_str)
    except json.JSONDecodeError as e:
        raise LLMParseError("merge", raw, str(e)) from e
    if not isinstance(data, dict):
        raise LLMParseError("merge", raw, "expected JSON object")

    action = str(data.get("action", "noop")).strip()
    if action not in ("merge", "noop"):
        action = "noop"
    if action == "noop":
        return {"action": "noop", "reason": str(data.get("reason", ""))}

    keep = data.get("keep")
    absorb = data.get("absorb") or []
    if not keep or not isinstance(absorb, list) or not absorb:
        raise LLMParseError("merge", raw, "action=merge but keep/absorb missing")
    keep = str(keep)
    norm_absorb = [str(x) for x in absorb if x]
    if not norm_absorb:
        raise LLMParseError("merge", raw, "action=merge but absorb empty")
    if keep in norm_absorb:
        raise LLMParseError("merge", raw, "keep must not be in absorb")

    merged_content = data.get("merged_content") or ""
    aliases = data.get("aliases_to_add") or []
    norm_aliases = [str(x) for x in aliases if isinstance(x, str) and x]

    return {
        "action": "merge",
        "keep": keep,
        "absorb": norm_absorb,
        "merged_content": str(merged_content),
        "aliases_to_add": norm_aliases,
        "reason": str(data.get("reason", "")),
    }

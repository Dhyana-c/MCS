"""purpose='split' 的 Prompt 包。

记忆 agent 的 ``split`` 工具（概念拆分·写图）：给定一个节点 + 其全部原边，让 LLM
判断该节点是否**耦合了多个本该独立的语义中心**，若是则产出拆分方案（产物 ``into`` +
产物间 ``relation`` + 每条原边归属 ``edges``），供 ``MemoryStore.split_concept`` 执行。
未耦合时返回 ``action=noop``、不执行（双重防误触发的第二道闸）。

两类耦合：

- **类别-特化**（``relation=is_a``）：content 把一个类别与该类别下的某种具体特化耦合
  （如"按摩"主要讲泰式特点 → 拆"按摩" parent + "泰式按摩" child）。
- **多实体误并**（``relation=none``）：content 是多个独立实体被当成一个
  （如"小明和小红" → 拆"小明" + "小红"，平级、无 is-a）。

**硬约束**：MUST 为每条原边在 ``edges`` 指定归属；跨两产物关系的原边（如"两人是夫妻"）
MUST 由 ``role=fact`` 产物承接（谓词落其 content、连两端）。

本 prompt 只产方案、不改图；执行 + 守门 + 原子事务由 ``MemoryStore.split_concept`` 负责。
``parse`` 只做结构校验；**漏边降级**（``edges`` 未覆盖的原边）在 ``MemoryStore._do_split``
执行侧做（那里才有原边集）——透明挂 parent + 提示，不拒执行（降级优于拒绝）。
"""

from __future__ import annotations

import json

from mcs.core.errors import LLMParseError
from mcs.utils.text_utils import extract_json

SYSTEM_PROMPT = (
    "你是知识图谱重构助手。判断给定的【一个概念节点 + 它的全部关联边】是否"
    "**耦合了多个本该独立的语义中心**——若是，给出拆分方案；若否，明确返回 noop。"
    "\n\n两类耦合（务必区分）："
    "\n① 类别-特化耦合（relation=is_a）：节点的 content 把【一个类别】和【该类别下的"
    "某种具体特化】混在一起。例：节点叫'按摩'，content 却主要讲泰式按摩的拉伸特点"
    "→ 拆成 '按摩'(大类, role=parent) + '泰式按摩'(特化, role=child)，relation=is_a。"
    "\n② 多实体误并（relation=none）：节点的 content 其实是【多个彼此独立的实体】被"
    "当成一个。例：节点叫'小明和小红'，content 同时讲两个人 → 拆成 '小明' + '小红'"
    "（均 role=sibling），relation=none，两者平级、无 is-a。"
    "\n\n硬约束（拆分时 MUST 遵守）："
    "\n- MUST 为【每一条原边】在 edges 里指定归属（counterpart 对应原边对端 name，"
    "to 为 into 里某产物的 name）。漏指的边会在执行侧透明挂 parent 并提示（不拒执行）。"
    "\n- 描述【两产物之间关系】的原边（如'两人是夫妻'、'泰式按摩属于按摩大类'），"
    "MUST 在 into 里产出一个 role=fact 节点承接（content 写谓词说法），再把该边在"
    "edges 里归到这个 fact 产物——不要强行归到某个概念产物而丢失关系语义。"
    "\n- 各产物的 content MUST 自洽、覆盖原 content 的相应部分，不丢失信息。"
    "\n\n何时不该拆（返回 action=noop）："
    "\n- 节点 content 自洽、只讲一个语义中心（即使 content 较长）。"
    "\n- 只是描述不准 / 过时——那是 content 重写，不是拆分。"
    "\n- 拿不准是否耦合——默认 noop（错拆比不拆糟：制造噪音节点 + 错分边）。"
    "\n\n**语言跟随**：拆分产物的 name / content MUST 沿用原节点的原文语言，MUST NOT 在拆分时翻译。"
    "\n\n只返回 JSON，不要解释。"
)

USER_TEMPLATE = (
    "待判定的节点及其全部原边（counterpart 为原边对端 name）:\n{material}\n\n"
    "聚焦语境:\n{focus}\n\n"
    "请判断该节点是否耦合了多个语义中心。返回 JSON：\n"
    '{{"action": "split|noop",\n'
    ' "into": [{{"name": "产物名", "content": "产物 content", "role": "parent|child|sibling|fact"}}],\n'
    ' "relation": "is_a|none",\n'
    ' "edges": [{{"counterpart": "原边对端 name", "to": "into 中某产物的 name"}}]}}\n'
    "action=noop 时 into/relation/edges 可省。split 时 into 非空、edges MUST 覆盖每条原边。"
)


def parse(raw: str) -> dict:
    """解析 split purpose 的 LLM 输出为结构化方案 dict。

    返回 ``{"action": "split"|"noop", "into": [...], "relation": ..., "edges": [...]}``。
    **只做结构校验**（字段存在 + 类型 + 取值域）；原边全覆盖校验在
    ``MemoryStore._do_split``（那里才有原边集）。
    """
    json_str = extract_json(raw)
    if not json_str:
        raise LLMParseError("split", raw, "no JSON found in response")
    try:
        data = json.loads(json_str)
    except json.JSONDecodeError as e:
        raise LLMParseError("split", raw, str(e)) from e
    if not isinstance(data, dict):
        raise LLMParseError("split", raw, "expected JSON object")

    action = str(data.get("action", "noop")).strip()
    if action not in ("split", "noop"):
        action = "noop"
    if action == "noop":
        return {"action": "noop"}

    into = data.get("into") or []
    if not isinstance(into, list) or not into:
        raise LLMParseError("split", raw, "action=split but into empty/missing")
    norm_into = []
    valid_roles = {"parent", "child", "sibling", "fact"}
    for item in into:
        if not isinstance(item, dict):
            continue
        name = item.get("name")
        if not name:
            continue
        role = str(item.get("role", "sibling")).strip()
        if role not in valid_roles:
            role = "sibling"
        norm_into.append(
            {"name": str(name), "content": str(item.get("content", "")), "role": role}
        )
    if not norm_into:
        raise LLMParseError("split", raw, "action=split but into has no valid items")

    relation = str(data.get("relation", "none")).strip()
    if relation not in ("is_a", "none"):
        relation = "none"

    edges = data.get("edges") or []
    norm_edges = []
    for item in edges:
        if not isinstance(item, dict):
            continue
        counterpart = item.get("counterpart")
        to = item.get("to")
        if counterpart and to:
            norm_edges.append({"counterpart": str(counterpart), "to": str(to)})

    return {
        "action": "split",
        "into": norm_into,
        "relation": relation,
        "edges": norm_edges,
    }

"""purpose='decide_hub' 的 Prompt 包。

写入阶段 ⑥ FanoutReducerPlugin 压缩插件。输入：焦点节点 + 全部一跳子节点。
输出：MultiHubDecision —— 多个社区划分，每社区按"合并同义 / 找关键概念 / 概括新概念"重组。
"""

from __future__ import annotations

import json

from mcs.core.decisions import Community, MultiHubDecision
from mcs.core.errors import LLMParseError
from mcs.utils.text_utils import strip_json_fence

SYSTEM_PROMPT = (
    "你是一个知识组织专家。给定一个中心节点和它的全部一跳子节点，"
    "把它们分成多个语义内聚的社区。每个社区按优先级重组：\n"
    "① 合并同义——把同义概念合并为一个\n"
    "② 找到关键概念——识别社区里的关键概念作组织中心，其余概念关联它\n"
    "③ 概括成新概念——无现成关键概念时，把这组概念概括成一个新概念\n"
    "概括出的新概念必须有语义内涵、可独立成义，禁止空洞聚合标签"
    "（如'信息碎片集合''综合信息枢纽'）。\n"
    "一个概念可以同时属于多个社区（重叠）。无法分类的概念留到 unassigned。"
)

USER_TEMPLATE = (
    "中心节点和它的全部一跳子节点:\n{material}\n\n"
    "请返回 JSON:\n"
    "  {{\n"
    '    "communities": [\n'
    "      {{\n"
    '        "theme": "社区主题",\n'
    '        "member_ids": ["id1", "id2", ...],\n'
    '        "strategy": "merge|key_concept|summarize",\n'
    '        "key_concept_id": "关键概念id（strategy=key_concept时）",\n'
    '        "summary": "概括内容（strategy=summarize时）"\n'
    "      }}\n"
    "    ],\n"
    '    "unassigned": ["无法分类的id"],\n'
    '    "reason": "划分理由"\n'
    "  }}\n"
    "只返回 JSON。member_ids 只需列出 id，不需要重复名称或内容。"
)


def parse(raw: str) -> MultiHubDecision:
    """解析 LLM 输出为 MultiHubDecision。

    含幻觉 id 过滤和确定性兜底。
    """
    try:
        data = json.loads(strip_json_fence(raw))
    except json.JSONDecodeError as e:
        raise LLMParseError("decide_hub", raw, str(e)) from e
    if not isinstance(data, dict):
        raise LLMParseError("decide_hub", raw, "expected JSON object")

    communities = []
    for c in data.get("communities", []):
        if not isinstance(c, dict):
            continue
        # 去重 member_ids
        member_ids = list(dict.fromkeys(c.get("member_ids", [])))
        communities.append(Community(
            theme=c.get("theme", ""),
            member_ids=member_ids,
            strategy=c.get("strategy", "summarize"),
            key_concept_id=c.get("key_concept_id"),
            summary=c.get("summary"),
        ))

    unassigned = data.get("unassigned", [])
    if isinstance(unassigned, list):
        unassigned = [str(x) for x in unassigned]
    else:
        unassigned = []

    return MultiHubDecision(
        communities=communities,
        unassigned_ids=unassigned,
        reason=data.get("reason", "") or "",
    )


def validate_and_repair(
    decision: MultiHubDecision,
    valid_ids: set[str],
) -> MultiHubDecision:
    """校验并修复 MultiHubDecision。

    - 过滤幻觉 id：只保留 valid_ids 中的 id
    - 确保所有成员都有归属（社区或 unassigned）
    - 空社区的处理

    Args:
        decision: 原始决策
        valid_ids: 有效的节点 id 集合（全部一跳子节点 id）

    Returns:
        校验后的决策
    """
    # 过滤幻觉 id
    validated_communities = []
    all_assigned = set()

    for comm in decision.communities:
        valid_members = [mid for mid in comm.member_ids if mid in valid_ids]
        if not valid_members:
            continue  # 空社区跳过

        # 过滤 key_concept_id
        key_id = comm.key_concept_id
        if key_id and key_id not in valid_ids:
            key_id = None
            comm = Community(
                theme=comm.theme,
                member_ids=valid_members,
                strategy="summarize",  # 退化为概括
                key_concept_id=None,
                summary=comm.summary,
            )
        else:
            comm.member_ids = valid_members

        validated_communities.append(comm)
        all_assigned.update(valid_members)

    # 确保 unassigned 也过滤
    valid_unassigned = [uid for uid in decision.unassigned_ids if uid in valid_ids]
    all_assigned.update(valid_unassigned)

    # 找出漏分的成员（确定性兜底：归入 unassigned）
    missing = valid_ids - all_assigned
    if missing:
        valid_unassigned.extend(missing)

    return MultiHubDecision(
        communities=validated_communities,
        unassigned_ids=valid_unassigned,
        reason=decision.reason,
    )

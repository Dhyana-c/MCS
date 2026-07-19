"""Prompt 注册表 - 按 purpose 组织 system / template / parse 三元组。

框架的 ``LLMInterface.get_prompt(purpose)`` 在没有用户覆盖时回退到这里。
第一期提供 9 个默认 purpose；用户可通过 ``LLMInterface.register_prompt``
或 ``MCSConfig.prompt_overrides`` 覆盖任意一个。
"""

from __future__ import annotations

from mcs.interfaces.llm import PromptBundle
from mcs.prompts import (
    adjudicate,
    decide_directions,
    decide_hub,
    extract_concepts,
    extract_work_events,
    gen_aliases,
    gen_graph_summary,
    gen_summary,
    generalize,
    judge_relations,
    merge,
    merge_content,
    navigate_hub,
    select_facts,
    select_nodes,
    split,
    synthesize,
)

DEFAULT_PROMPTS: dict[str, PromptBundle] = {
    # json_output=True：写管线抽取三件套开启后端 JSON 模式（prompt 明确要求 JSON、
    # 解析器已容忍对象包装）——根治长输出语法失误致 salvage 丢对象（英文语料引号密集时高发）
    "extract_concepts": PromptBundle(
        system=extract_concepts.SYSTEM_PROMPT,
        template=extract_concepts.USER_TEMPLATE,
        parse=extract_concepts.parse,
        json_output=True,
    ),
    "extract_work_events": PromptBundle(
        system=extract_work_events.SYSTEM_PROMPT,
        template=extract_work_events.USER_TEMPLATE,
        parse=extract_work_events.parse,
        json_output=True,
    ),
    "judge_relations": PromptBundle(
        system=judge_relations.SYSTEM_PROMPT,
        template=judge_relations.USER_TEMPLATE,
        parse=judge_relations.parse,
        json_output=True,
    ),
    "decide_directions": PromptBundle(
        system=decide_directions.SYSTEM_PROMPT,
        template=decide_directions.USER_TEMPLATE,
        parse=decide_directions.parse,
    ),
    "decide_hub": PromptBundle(
        system=decide_hub.SYSTEM_PROMPT,
        template=decide_hub.USER_TEMPLATE,
        parse=decide_hub.parse,
    ),
    "navigate_hub": PromptBundle(
        system=navigate_hub.SYSTEM_PROMPT,
        template=navigate_hub.USER_TEMPLATE,
        parse=navigate_hub.parse,
    ),
    "synthesize": PromptBundle(
        system=synthesize.SYSTEM_PROMPT,
        template=synthesize.USER_TEMPLATE,
        parse=synthesize.parse,
    ),
    "gen_aliases": PromptBundle(
        system=gen_aliases.SYSTEM_PROMPT,
        template=gen_aliases.USER_TEMPLATE,
        parse=gen_aliases.parse,
    ),
    "gen_summary": PromptBundle(
        system=gen_summary.SYSTEM_PROMPT,
        template=gen_summary.USER_TEMPLATE,
        parse=gen_summary.parse,
    ),
    "gen_graph_summary": PromptBundle(
        system=gen_graph_summary.SYSTEM_PROMPT,
        template=gen_graph_summary.USER_TEMPLATE,
        parse=gen_graph_summary.parse,
    ),
    "select_nodes": PromptBundle(
        system=select_nodes.SYSTEM_PROMPT,
        template=select_nodes.USER_TEMPLATE,
        parse=select_nodes.parse,
    ),
    "select_nodes_batch": PromptBundle(
        system=select_nodes.SYSTEM_PROMPT,
        template=select_nodes.BATCH_USER_TEMPLATE,
        parse=select_nodes.parse,
    ),
    "select_facts_write": PromptBundle(
        system=select_facts.WRITE_SYSTEM_PROMPT,
        template=select_facts.WRITE_USER_TEMPLATE,
        parse=select_facts.parse,
    ),
    "generalize": PromptBundle(
        system=generalize.SYSTEM_PROMPT,
        template=generalize.USER_TEMPLATE,
        parse=generalize.parse,
    ),
    "adjudicate": PromptBundle(
        system=adjudicate.SYSTEM_PROMPT,
        template=adjudicate.USER_TEMPLATE,
        parse=adjudicate.parse,
    ),
    "split": PromptBundle(
        system=split.SYSTEM_PROMPT,
        template=split.USER_TEMPLATE,
        parse=split.parse,
    ),
    "merge": PromptBundle(
        system=merge.SYSTEM_PROMPT,
        template=merge.USER_TEMPLATE,
        parse=merge.parse,
    ),
    "merge_content": PromptBundle(
        system=merge_content.SYSTEM_PROMPT,
        template=merge_content.USER_TEMPLATE,
        parse=merge_content.parse,
    ),
}


__all__ = ["DEFAULT_PROMPTS", "PromptBundle"]

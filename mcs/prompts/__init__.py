"""Prompt 注册表 - 按 purpose 组织 system / template / parse 三元组。

框架的 ``LLMInterface.get_prompt(purpose)`` 在没有用户覆盖时回退到这里。
第一期提供 9 个默认 purpose；用户可通过 ``LLMInterface.register_prompt``
或 ``MCSConfig.prompt_overrides`` 覆盖任意一个。
"""

from __future__ import annotations

from mcs.interfaces.llm import PromptBundle
from mcs.prompts import (
    arbitrate,
    decide_directions,
    decide_hub,
    extract_concepts,
    gen_aliases,
    gen_graph_summary,
    gen_summary,
    judge_relations,
    navigate_hub,
    select_facts,
    select_nodes,
    synthesize,
)

DEFAULT_PROMPTS: dict[str, PromptBundle] = {
    "extract_concepts": PromptBundle(
        system=extract_concepts.SYSTEM_PROMPT,
        template=extract_concepts.USER_TEMPLATE,
        parse=extract_concepts.parse,
    ),
    "judge_relations": PromptBundle(
        system=judge_relations.SYSTEM_PROMPT,
        template=judge_relations.USER_TEMPLATE,
        parse=judge_relations.parse,
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
    "arbitrate": PromptBundle(
        system=arbitrate.SYSTEM_PROMPT,
        template=arbitrate.USER_TEMPLATE,
        parse=arbitrate.parse,
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
    "select_facts": PromptBundle(
        system=select_facts.SYSTEM_PROMPT,
        template=select_facts.USER_TEMPLATE,
        parse=select_facts.parse,
    ),
}


__all__ = ["DEFAULT_PROMPTS", "PromptBundle"]

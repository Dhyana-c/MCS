"""Prompt registry - bundles ``system / template / parse`` per purpose.

The framework's ``LLMInterface.get_prompt(purpose)`` falls back here when
no user override is registered. Phase 1 ships 9 default purposes; users
can override any of them via ``LLMInterface.register_prompt`` or via
``MCSConfig.prompt_overrides``.
"""

from __future__ import annotations

from mcs.interfaces.llm import PromptBundle
from mcs.prompts import (
    arbitrate,
    decide_directions,
    decide_hub,
    extract_concepts,
    gen_aliases,
    gen_summary,
    judge_relations,
    navigate_hub,
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
}


__all__ = ["DEFAULT_PROMPTS", "PromptBundle"]

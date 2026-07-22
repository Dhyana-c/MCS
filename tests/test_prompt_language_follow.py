"""prompt-language-following 的单测：

1. node_class 枚举英化（prompt 暴露 concept/fact）+ parse 双接受（英文/中文/大小写/未知/缺省）
2. 存储层常量 CLASS_* 取值不变（仍中文常量，非 BREAKING）
3. 13 个 must/optional prompt 均含「语言跟随」指令；4 个 no prompt（纯 id/编号）不含
4. gen_aliases 示例去中文化（不再以中文译名作示范）
5. LANGUAGE_FOLLOW_PROMPT 保留 `# 回答语言` 首行 + 新增主动对齐

integration（真实 deepseek 验英文不翻译）见 test_deepseek_real_integration.py。
"""

from __future__ import annotations

import pytest

from mcs.entities.graph import (
    CLASS_CONCEPT,
    CLASS_EVENT,
    CLASS_FACT,
    CLASS_SOURCE,
)
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
from mcs_agent.loop import LANGUAGE_FOLLOW_PROMPT


# === 1. node_class parse 双接受（英文/中文/大小写/未知/缺省）===


def test_extract_concepts_parse_maps_english_enum():
    """英文 concept/fact → 中文常量 CLASS_CONCEPT/CLASS_FACT。"""
    assert parse_node_class(extract_concepts, "fact") == CLASS_FACT
    assert parse_node_class(extract_concepts, "concept") == CLASS_CONCEPT


def test_extract_concepts_parse_backward_compat_chinese():
    """中文 概念/事实（旧 LLM 输出 / 旧库）仍正确映射，向后兼容。"""
    assert parse_node_class(extract_concepts, "事实") == CLASS_FACT
    assert parse_node_class(extract_concepts, "概念") == CLASS_CONCEPT


def test_extract_concepts_parse_case_insensitive():
    """大小写不敏感（Concept/FACT 等变体也接受）。"""
    assert parse_node_class(extract_concepts, "FACT") == CLASS_FACT
    assert parse_node_class(extract_concepts, "Concept") == CLASS_CONCEPT


def test_extract_concepts_parse_unknown_defaults_concept():
    """未知 / 缺省 node_class 回退为概念（保既有行为）。"""
    assert parse_node_class(extract_concepts, "weird") == CLASS_CONCEPT
    raw = '[{"name": "X", "content": "c"}]'  # 缺 node_class 字段
    assert extract_concepts.parse(raw)[0].node_class == CLASS_CONCEPT


def test_judge_relations_parse_maps_english_enum():
    assert parse_node_class(judge_relations, "fact") == CLASS_FACT
    assert parse_node_class(judge_relations, "concept") == CLASS_CONCEPT


def test_judge_relations_parse_backward_compat_chinese():
    assert parse_node_class(judge_relations, "事实") == CLASS_FACT
    assert parse_node_class(judge_relations, "概念") == CLASS_CONCEPT


def test_judge_relations_parse_case_insensitive_and_unknown():
    assert parse_node_class(judge_relations, "FACT") == CLASS_FACT
    assert parse_node_class(judge_relations, "nonsense") == CLASS_CONCEPT


def parse_node_class(module, node_class_value: str) -> str:
    """用 module.parse 跑一条只含 node_class 的 JSON，返回解析后的 node_class 常量。

    extract_concepts 用 name/content/node_class；judge_relations 用 action/concept_name/node_class。
    自动适配两种 schema。
    """
    if module is judge_relations:
        raw = (
            '[{"action": "create", "concept_name": "X", '
            f'"node_class": "{node_class_value}"}}]'
        )
        return module.parse(raw)[0].node_class
    raw = (
        f'[{{"name": "X", "content": "c", "node_class": "{node_class_value}"}}]'
    )
    return module.parse(raw)[0].node_class


# === 2. 存储层常量不变（非 BREAKING 的根本保证）===


def test_node_class_storage_constants_unchanged():
    """存储层 node.node_class 取值仍为中文常量——本次只动 prompt 字面 + parse 映射。"""
    assert CLASS_CONCEPT == "概念"
    assert CLASS_FACT == "事实"
    assert CLASS_EVENT == "事件"
    assert CLASS_SOURCE == "source"


# === 3. prompt 枚举英化（extract_concepts / judge_relations 暴露 concept/fact）===


def test_extract_concepts_prompt_uses_english_node_class_enum():
    assert 'node_class="concept"' in extract_concepts.SYSTEM_PROMPT
    assert 'node_class="fact"' in extract_concepts.SYSTEM_PROMPT
    assert '"node_class": "concept|fact"' in extract_concepts.USER_TEMPLATE
    # 旧中文枚举字面值不再出现在 prompt 协议层
    assert 'node_class="概念"' not in extract_concepts.SYSTEM_PROMPT
    assert 'node_class="事实"' not in extract_concepts.SYSTEM_PROMPT
    assert "概念|事实" not in extract_concepts.USER_TEMPLATE


def test_judge_relations_prompt_uses_english_node_class_enum():
    assert '"node_class": "concept|fact"' in judge_relations.USER_TEMPLATE
    assert "概念|事实" not in judge_relations.USER_TEMPLATE


# === 4. must / optional prompt 含语言跟随；no prompt 不含 ===


MUST_LANG_PROMPTS = [
    ("extract_concepts", extract_concepts.SYSTEM_PROMPT),
    ("extract_work_events", extract_work_events.SYSTEM_PROMPT),
    ("judge_relations", judge_relations.SYSTEM_PROMPT),
    ("decide_hub", decide_hub.SYSTEM_PROMPT),
    ("gen_summary", gen_summary.SYSTEM_PROMPT),
    ("gen_graph_summary", gen_graph_summary.SYSTEM_PROMPT),
    ("synthesize", synthesize.SYSTEM_PROMPT),
    ("merge_content", merge_content.SYSTEM_PROMPT),
    ("gen_aliases", gen_aliases.SYSTEM_PROMPT),
    ("split", split.SYSTEM_PROMPT),
    ("merge", merge.SYSTEM_PROMPT),
]

OPTIONAL_LANG_PROMPTS = [
    ("generalize", generalize.SYSTEM_PROMPT),
    ("adjudicate", adjudicate.SYSTEM_PROMPT),
]


@pytest.mark.parametrize("name,system_prompt", MUST_LANG_PROMPTS)
def test_must_prompt_has_language_following(name, system_prompt):
    assert "语言跟随" in system_prompt, f"{name} 缺语言跟随指令"


@pytest.mark.parametrize("name,system_prompt", OPTIONAL_LANG_PROMPTS)
def test_optional_prompt_has_language_following(name, system_prompt):
    assert "语言跟随" in system_prompt, f"{name} 缺语言跟随指令"


def test_no_lang_prompts_have_no_language_following():
    """纯 id / 编号输出的 prompt 无需语言跟随（不该被误加）。"""
    assert "语言跟随" not in navigate_hub.SYSTEM_PROMPT
    assert "语言跟随" not in decide_directions.SYSTEM_PROMPT
    assert "语言跟随" not in select_nodes.SYSTEM_PROMPT
    assert "语言跟随" not in select_facts.WRITE_SYSTEM_PROMPT


# === 5. gen_aliases 示例去中文化 ===


def test_gen_aliases_example_language_neutral():
    """旧中文示范 ['AAPL','苹果公司','苹果'] 已去除，换语言中立示例。"""
    assert "苹果公司" not in gen_aliases.USER_TEMPLATE
    assert "苹果" not in gen_aliases.USER_TEMPLATE
    # 新示例存在且非中文译名诱导
    assert "United States" in gen_aliases.USER_TEMPLATE


# === 6. LANGUAGE_FOLLOW_PROMPT 保留首行 + 新增主动对齐 ===


def test_language_follow_prompt_keeps_header():
    """test_agent_loop.test_language_follow_appended_to_any_system_prompt 依赖 # 回答语言 首行。"""
    assert LANGUAGE_FOLLOW_PROMPT.startswith("# 回答语言")


def test_language_follow_prompt_proactive_alignment():
    """增强：不确定用户语言时先据用户消息判断（主动对齐），非仅被动转述。"""
    assert "主动对齐" in LANGUAGE_FOLLOW_PROMPT or "先据用户消息" in LANGUAGE_FOLLOW_PROMPT

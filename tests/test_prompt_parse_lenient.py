"""Parser 容错回归：LLM 偶尔返回单个对象（而非数组）也应被接受。"""

from __future__ import annotations

import pytest

from mcs.core.errors import LLMParseError
from mcs.prompts.adjudicate import parse as parse_adjudicate
from mcs.prompts.extract_concepts import parse as parse_concepts
from mcs.prompts.generalize import parse as parse_generalize
from mcs.prompts.judge_relations import parse as parse_relations
from mcs.prompts.navigate_hub import parse as parse_navigate_hub


def test_extract_concepts_accepts_single_object():
    raw = '{"name": "Ed Wood", "content": "An American filmmaker.", "relation_hints": []}'
    result = parse_concepts(raw)
    assert len(result) == 1
    assert result[0].name == "Ed Wood"


def test_extract_concepts_accepts_fenced_single_object():
    raw = '```json\n{"name": "X", "content": "c"}\n```'
    result = parse_concepts(raw)
    assert len(result) == 1
    assert result[0].name == "X"


def test_extract_concepts_still_accepts_array():
    raw = '[{"name": "A", "content": "a"}, {"name": "B", "content": "b"}]'
    result = parse_concepts(raw)
    assert [c.name for c in result] == ["A", "B"]


def test_judge_relations_accepts_single_object():
    raw = '{"action": "create", "concept_name": "X", "edges_to": []}'
    result = parse_relations(raw)
    assert len(result) == 1
    assert result[0].action == "create"
    assert result[0].concept.name == "X"


def test_judge_relations_parses_edges_to_names():
    # list[dict] with target_name（统一模型无 label，parse 剥离 LLM 残留的 label）
    raw = (
        '[{"action": "create", "concept_name": "苹果公司", '
        '"edges_to_names": [{"target_name": "iPhone", "label": "生产"}, '
        '{"target_name": "乔布斯", "label": "创立"}]}]'
    )
    result = parse_relations(raw)
    assert result[0].edges_to_names == [
        {"target_name": "iPhone"},
        {"target_name": "乔布斯"},
    ]


def test_judge_relations_edges_to_names_backward_compat():
    # 旧格式：list[str] 自动转换为 dict（无 label）
    raw = (
        '[{"action": "create", "concept_name": "苹果公司", '
        '"edges_to_names": ["iPhone", "乔布斯"]}]'
    )
    result = parse_relations(raw)
    assert result[0].edges_to_names == [
        {"target_name": "iPhone"},
        {"target_name": "乔布斯"},
    ]


def test_judge_relations_edges_to_names_defaults_empty():
    raw = '{"action": "create", "concept_name": "X"}'
    result = parse_relations(raw)
    assert result[0].edges_to_names == []


def test_judge_relations_edges_to_names_accepts_aliases():
    # 容忍 related_concepts / edges_to_concepts 别名（旧格式 str 自动转 dict）
    raw = '{"action": "create", "concept_name": "X", "related_concepts": ["Y"]}'
    result = parse_relations(raw)
    assert result[0].edges_to_names == [{"target_name": "Y"}]


def test_navigate_hub_salvages_truncated_array():
    """LLM 输出因 max_tokens 截断成未闭合数组时，抢救已闭合的 id、丢弃尾部残片。"""
    raw = '["a1b2","c3d4","e5f6'  # 第三个 id 被截断（未闭合引号）
    assert parse_navigate_hub(raw) == ["a1b2", "c3d4"]


def test_navigate_hub_accepts_valid_array():
    assert parse_navigate_hub('["id1","id2"]') == ["id1", "id2"]


def test_navigate_hub_empty_array():
    assert parse_navigate_hub("[]") == []


def test_navigate_hub_strips_prefix():
    """LLM 加了 'JSON:' 之类前缀也能解析。"""
    assert parse_navigate_hub("JSON:\n[]") == []
    assert parse_navigate_hub('JSON:\n["u1","u2"]') == ["u1", "u2"]


def test_navigate_hub_object_array():
    """LLM 返回对象数组 [{'id':..}] 时抽出 id。"""
    assert parse_navigate_hub('[{"id":"u1"},{"id":"u2"}]') == ["u1", "u2"]


def test_navigate_hub_object_wrapping_list():
    """LLM 返回 {'ids':[..]} 包裹时抽出列表。"""
    assert parse_navigate_hub('{"ids":["u1","u2"]}') == ["u1", "u2"]


def test_navigate_hub_garbage_returns_empty_not_raises():
    """完全不规整 → 返回 []，绝不抛异常（不拖垮 query）。"""
    assert parse_navigate_hub("抱歉，我无法确定") == []
    assert parse_navigate_hub("") == []


# === generalize / adjudicate（agent 只读语义判断工具的 purpose） ===


def test_generalize_parse_strips_text():
    assert parse_generalize("  它们都是哺乳类宠物\n") == "它们都是哺乳类宠物"


def test_generalize_parse_empty_raises():
    """空白响应（无实质结论）→ LLMParseError。"""
    with pytest.raises(LLMParseError):
        parse_generalize("   \n  ")


def test_generalize_parse_non_string_raises():
    with pytest.raises(LLMParseError):
        parse_generalize(None)  # type: ignore[arg-type]


def test_adjudicate_parse_dict():
    assert parse_adjudicate('{"adopt": ["f1"], "reason": "更近背书"}') == {
        "adopt": ["f1"],
        "reason": "更近背书",
    }


def test_adjudicate_parse_fenced():
    assert parse_adjudicate('```json\n{"adopt": ["f1", "f2"], "reason": "r"}\n```') == {
        "adopt": ["f1", "f2"],
        "reason": "r",
    }


def test_adjudicate_parse_defaults_empty_fields():
    """缺 adopt / reason → 容错为 [] / ''（非抛）。"""
    assert parse_adjudicate("{}") == {"adopt": [], "reason": ""}


def test_adjudicate_parse_bad_json_raises():
    with pytest.raises(LLMParseError):
        parse_adjudicate("not json")


def test_adjudicate_parse_non_object_raises():
    with pytest.raises(LLMParseError):
        parse_adjudicate('["f1"]')


def test_adjudicate_parse_adopt_not_string_array_raises():
    with pytest.raises(LLMParseError):
        parse_adjudicate('{"adopt": "f1", "reason": "r"}')  # adopt 非数组
    with pytest.raises(LLMParseError):
        parse_adjudicate('{"adopt": [1, 2], "reason": "r"}')  # 元素非字符串

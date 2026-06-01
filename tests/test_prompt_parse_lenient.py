"""Parser 容错回归：LLM 偶尔返回单个对象（而非数组）也应被接受。"""

from __future__ import annotations

from mcs.prompts.extract_concepts import parse as parse_concepts
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


def test_navigate_hub_salvages_truncated_array():
    """LLM 输出因 max_tokens 截断成未闭合数组时，抢救已闭合的 id、丢弃尾部残片。"""
    raw = '["a1b2","c3d4","e5f6'  # 第三个 id 被截断（未闭合引号）
    assert parse_navigate_hub(raw) == ["a1b2", "c3d4"]


def test_navigate_hub_accepts_valid_array():
    assert parse_navigate_hub('["id1","id2"]') == ["id1", "id2"]


def test_navigate_hub_empty_array():
    assert parse_navigate_hub("[]") == []

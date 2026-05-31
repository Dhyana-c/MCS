"""Parser 容错回归：LLM 偶尔返回单个对象（而非数组）也应被接受。"""

from __future__ import annotations

from mcs.prompts.extract_concepts import parse as parse_concepts
from mcs.prompts.judge_relations import parse as parse_relations


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

# -*- coding: utf-8 -*-
"""LLM JSON 模式测试（PromptBundle.json_output → 后端 response_format）。

回归背景：multihop agent 建图 1009 次抽取调用里 10 次 JSON 语法失误（未转义引号/
漏逗号，英文语料高发）→ salvage 丢对象。根治 = 写管线抽取三件套声明 json_output，
DeepSeek 开 response_format=json_object；解析器容忍任意键包装（json 模式下模型
可能不吐裸数组）。
"""

import json
from types import SimpleNamespace

from mcs.interfaces.llm import LLMInterface, PromptBundle
from mcs.plugins.llm.deepseek_llm import DeepSeekLLMPlugin
from mcs.prompts import DEFAULT_PROMPTS
from mcs.prompts.extract_concepts import parse as concepts_parse
from mcs.prompts.extract_work_events import parse as work_events_parse
from mcs.prompts.judge_relations import parse as judge_parse


# ---------- PromptBundle 声明 ----------


def test_json_output_defaults_false():
    b = PromptBundle(system="s", template="t", parse=lambda r: r)
    assert b.json_output is False


def test_write_extraction_purposes_declare_json_output():
    """写管线抽取三件套开 JSON 模式；纯文本 purpose 必须保持关闭。"""
    for purpose in ("extract_concepts", "judge_relations", "extract_work_events"):
        assert DEFAULT_PROMPTS[purpose].json_output is True, purpose
    for purpose in ("gen_summary", "synthesize", "gen_graph_summary"):
        assert DEFAULT_PROMPTS[purpose].json_output is False, purpose


# ---------- call() 置位 + register_prompt 继承 ----------


class _CapturingLLM(LLMInterface):
    def __init__(self):
        super().__init__()
        self.seen_json_flags: list[bool] = []

    def get_name(self) -> str:
        return "capturing"

    def _raw_call(self, system: str, user: str) -> str:
        self.seen_json_flags.append(getattr(self, "_json_output", False))
        return "[]"


def test_call_sets_json_output_per_bundle():
    llm = _CapturingLLM()
    llm.call("extract_concepts", free_args={"text": "x"})       # json_output=True
    llm.register_prompt("gen_summary", system="s", template="{material}",
                        parser=lambda r: r)
    llm.call("gen_summary", free_args={})                        # 文本 purpose → False
    assert llm.seen_json_flags == [True, False]


def test_register_prompt_preserves_json_output():
    """只覆盖 prompt 文本不会静默关掉 JSON 模式；显式传参可覆盖。"""
    llm = _CapturingLLM()
    llm.register_prompt("extract_concepts", system="新 system")
    assert llm.get_prompt("extract_concepts").json_output is True
    llm.register_prompt("extract_concepts", json_output=False)
    assert llm.get_prompt("extract_concepts").json_output is False


# ---------- DeepSeek response_format 注入 ----------


class _FakeCompletions:
    def __init__(self):
        self.kwargs: dict | None = None

    def create(self, **kwargs):
        self.kwargs = kwargs
        msg = SimpleNamespace(content="[]")
        return SimpleNamespace(choices=[SimpleNamespace(message=msg)])


def _fake_client():
    comp = _FakeCompletions()
    return SimpleNamespace(chat=SimpleNamespace(completions=comp)), comp


def test_deepseek_adds_response_format_when_json_output():
    plugin = DeepSeekLLMPlugin({"api_key": "x"})
    plugin.client, comp = _fake_client()
    plugin._json_output = True
    plugin._do_raw_call("sys", "user")
    assert comp.kwargs["response_format"] == {"type": "json_object"}


def test_deepseek_omits_response_format_by_default():
    plugin = DeepSeekLLMPlugin({"api_key": "x"})
    plugin.client, comp = _fake_client()
    plugin._do_raw_call("sys", "user")  # 未置位 → 不带
    assert "response_format" not in comp.kwargs
    plugin._json_output = False
    plugin._do_raw_call("sys", "user")
    assert "response_format" not in comp.kwargs


# ---------- 解析器容忍任意键包装（json 模式产物） ----------


def test_concepts_parse_unwraps_arbitrary_key():
    raw = json.dumps({"nodes": [
        {"name": "A", "content": "a", "node_class": "概念"},
        {"name": "B", "content": "b", "node_class": "事实"},
    ]}, ensure_ascii=False)
    got = concepts_parse(raw)
    assert [c.name for c in got] == ["A", "B"]


def test_work_events_parse_unwraps_arbitrary_key():
    raw = json.dumps({"叙事事件": [
        {"name": "e1", "content": "c", "narr_timestamp": "200 年", "participants": []},
    ]}, ensure_ascii=False)
    got = work_events_parse(raw)
    assert len(got) == 1 and got[0].narr_timestamp == "200 年"


def test_judge_parse_unwraps_arbitrary_key():
    raw = json.dumps({"judgements": [
        {"action": "create", "concept_name": "X"},
    ]}, ensure_ascii=False)
    got = judge_parse(raw)
    assert len(got) == 1 and got[0].action == "create"


def test_concepts_parse_single_object_still_works():
    """既有语义不回归：无列表值的 dict 仍按单概念对象处理。"""
    raw = json.dumps({"name": "Solo", "content": "s", "node_class": "概念"},
                     ensure_ascii=False)
    got = concepts_parse(raw)
    assert len(got) == 1 and got[0].name == "Solo"

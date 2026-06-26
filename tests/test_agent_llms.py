"""LLM 后端测试：AssistantMessage / CallableAgentLLM / anthropic 翻译纯函数。

全部 mock / 纯函数，不连真实 API、不需 anthropic SDK 安装。
"""

from __future__ import annotations

import sys
import types

import pytest

from mcs_agent.llms import AGENT_LLM_REGISTRY, PROVIDER_TO_MCS_LLM, CallableAgentLLM, OpenAIAgentLLM
from mcs_agent.llms.anthropic import AnthropicAgentLLM, _openai_tools_to_anthropic, _openai_to_anthropic
from mcs_agent.llms.base import AgentLLMInterface, AssistantMessage
from mcs_agent.trace import LLMCallTrace


# === AssistantMessage ===


def test_assistant_message_defaults():
    m = AssistantMessage(content="hi")
    assert m.content == "hi"
    assert m.tool_calls == []
    assert m.trace is None


def test_assistant_message_trace_field():
    trace = LLMCallTrace(
        model="m", latency_ms=1.0, token_usage=None, timestamp=0.0,
        request_summary=[], response_summary="", tool_call_names=[],
    )
    m = AssistantMessage(content="x", tool_calls=[{"id": "1"}], trace=trace)
    assert m.trace is trace


# === CallableAgentLLM（裸 callable 自动适配，保既有注入测试零改动） ===


def test_callable_agent_llm_wraps_bare_callable():
    def llm_call(msgs, tools):
        return {"role": "assistant", "content": "hello", "tool_calls": []}

    msg = CallableAgentLLM(llm_call).chat([{"role": "user", "content": "x"}], [])
    assert isinstance(msg, AssistantMessage)
    assert msg.content == "hello"
    assert msg.tool_calls == []
    assert msg.trace is None  # 无 _trace 键


def test_callable_agent_llm_extracts_trace_from_dict():
    trace = LLMCallTrace(
        model="m", latency_ms=1.0, token_usage=None, timestamp=0.0,
        request_summary=[], response_summary="", tool_call_names=[],
    )

    def llm_call(msgs, tools):
        return {
            "content": "hi",
            "tool_calls": [{"id": "1", "type": "function", "function": {"name": "x", "arguments": "{}"}}],
            "_trace": trace,
        }

    msg = CallableAgentLLM(llm_call).chat([], [])
    assert msg.trace is trace  # _trace 提为一等字段
    assert msg.tool_calls[0]["function"]["name"] == "x"


def test_callable_agent_llm_rejects_non_dict():
    with pytest.raises(TypeError):
        CallableAgentLLM(lambda m, t: "not a dict").chat([], [])


# === registry ===


def test_registry_has_three_providers():
    assert set(AGENT_LLM_REGISTRY) == {"deepseek", "ollama", "claude"}
    assert AGENT_LLM_REGISTRY["deepseek"] is OpenAIAgentLLM
    assert AGENT_LLM_REGISTRY["ollama"] is OpenAIAgentLLM
    assert set(PROVIDER_TO_MCS_LLM) == {"deepseek", "ollama", "claude"}


def test_backends_are_interface():
    for cls in AGENT_LLM_REGISTRY.values():
        assert issubclass(cls, AgentLLMInterface)


# === anthropic 翻译纯函数 ===


def test_anthropic_system_extracted():
    sys_, anth = _openai_to_anthropic(
        [{"role": "system", "content": "S"}, {"role": "user", "content": "hi"}]
    )
    assert sys_ == "S"
    assert anth == [{"role": "user", "content": "hi"}]


def test_anthropic_multi_system_merged():
    sys_, anth = _openai_to_anthropic(
        [{"role": "system", "content": "A"}, {"role": "system", "content": "B"}, {"role": "user", "content": "u"}]
    )
    assert sys_ == "A\n\nB"


def test_anthropic_assistant_tool_use_block():
    msgs = [
        {
            "role": "assistant", "content": None,
            "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "search", "arguments": '{"query":"x"}'}}],
        }
    ]
    _, anth = _openai_to_anthropic(msgs)
    assert anth[0]["content"][0] == {"type": "tool_use", "id": "c1", "name": "search", "input": {"query": "x"}}


def test_anthropic_assistant_content_none_no_text_block():
    msgs = [
        {
            "role": "assistant", "content": None,
            "tool_calls": [{"id": "1", "type": "function", "function": {"name": "x", "arguments": "{}"}}],
        }
    ]
    _, anth = _openai_to_anthropic(msgs)
    assert all(b["type"] == "tool_use" for b in anth[0]["content"])  # 无空 text 块


def test_anthropic_assistant_text_plus_tool_use():
    msgs = [
        {
            "role": "assistant", "content": "thinking",
            "tool_calls": [{"id": "1", "type": "function", "function": {"name": "x", "arguments": "{}"}}],
        }
    ]
    _, anth = _openai_to_anthropic(msgs)
    assert anth[0]["content"][0] == {"type": "text", "text": "thinking"}
    assert anth[0]["content"][1]["type"] == "tool_use"


def test_anthropic_tool_result_into_user_with_id():
    msgs = [
        {"role": "assistant", "content": None, "tool_calls": [{"id": "c1", "type": "function", "function": {"name": "x", "arguments": "{}"}}]},
        {"role": "tool", "tool_call_id": "c1", "content": "R"},
    ]
    _, anth = _openai_to_anthropic(msgs)
    assert anth[1] == {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "c1", "content": "R"}]}


def test_anthropic_multi_tool_results_merge_into_one_user():
    msgs = [
        {"role": "user", "content": "q"},
        {
            "role": "assistant", "content": None,
            "tool_calls": [
                {"id": "a", "type": "function", "function": {"name": "x", "arguments": "{}"}},
                {"id": "b", "type": "function", "function": {"name": "y", "arguments": "{}"}},
            ],
        },
        {"role": "tool", "tool_call_id": "a", "content": "ra"},
        {"role": "tool", "tool_call_id": "b", "content": "rb"},
    ]
    _, anth = _openai_to_anthropic(msgs)
    assert anth[2]["role"] == "user"
    assert [b["tool_use_id"] for b in anth[2]["content"]] == ["a", "b"]


def test_anthropic_tools_translation():
    tools = [
        {
            "type": "function",
            "function": {"name": "search", "description": "d", "parameters": {"type": "object", "properties": {"q": {"type": "string"}}}},
        }
    ]
    out = _openai_tools_to_anthropic(tools)
    assert out[0] == {
        "name": "search", "description": "d",
        "input_schema": {"type": "object", "properties": {"q": {"type": "string"}}},
    }


def test_anthropic_response_to_openai_tool_calls():
    """_anthropic_to_openai：text block → content，tool_use block → openai tool_calls。"""
    from mcs_agent.llms.anthropic import _anthropic_to_openai

    class _Block:
        def __init__(self, type, **kw):
            self.type = type
            self.__dict__.update(kw)

    class _Resp:
        content = [_Block("text", text="ans"), _Block("tool_use", id="t1", name="search", input={"q": "x"})]

    content, tool_calls = _anthropic_to_openai(_Resp())
    assert content == "ans"
    assert tool_calls == [
        {"id": "t1", "type": "function", "function": {"name": "search", "arguments": '{"q": "x"}'}}
    ]


# === client 缓存（多次 chat 复用同一 SDK client，不每次重建连接池） ===


def test_openai_client_built_once(monkeypatch):
    constructed: list[dict] = []

    def _make_resp():
        msg = types.SimpleNamespace(
            model_dump=lambda: {"role": "assistant", "content": "hi", "tool_calls": []}
        )
        usage = types.SimpleNamespace(prompt_tokens=1, completion_tokens=1, total_tokens=2)
        return types.SimpleNamespace(choices=[types.SimpleNamespace(message=msg)], usage=usage)

    class _FakeOpenAI:
        def __init__(self, **kw):
            constructed.append(kw)
            self.chat = types.SimpleNamespace(
                completions=types.SimpleNamespace(create=lambda **k: _make_resp())
            )

    fake_mod = types.ModuleType("openai")
    fake_mod.OpenAI = _FakeOpenAI
    monkeypatch.setitem(sys.modules, "openai", fake_mod)

    backend = OpenAIAgentLLM("m", "k", base_url="http://x")
    backend.chat([{"role": "user", "content": "a"}], [])
    backend.chat([{"role": "user", "content": "b"}], [])
    assert len(constructed) == 1  # client 仅构造一次
    assert constructed[0] == {"api_key": "k", "base_url": "http://x"}


def test_anthropic_client_built_once_auth_token_preferred(monkeypatch):
    constructed: list[dict] = []

    def _make_resp():
        block = types.SimpleNamespace(type="text", text="hi")
        usage = types.SimpleNamespace(input_tokens=1, output_tokens=1)
        return types.SimpleNamespace(content=[block], usage=usage)

    class _FakeAnthropic:
        def __init__(self, **kw):
            constructed.append(kw)
            self.messages = types.SimpleNamespace(create=lambda **k: _make_resp())

    fake_mod = types.ModuleType("anthropic")
    fake_mod.Anthropic = _FakeAnthropic
    monkeypatch.setitem(sys.modules, "anthropic", fake_mod)

    backend = AnthropicAgentLLM("m", api_key="k", auth_token="bt")
    backend.chat([{"role": "user", "content": "a"}], [])
    backend.chat([{"role": "user", "content": "b"}], [])
    assert len(constructed) == 1  # client 仅构造一次
    assert constructed[0] == {"auth_token": "bt", "base_url": None}  # auth_token 优先于 api_key

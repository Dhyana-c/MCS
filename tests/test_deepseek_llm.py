"""DeepSeek 插件回归：_raw_call 必须传 max_tokens，避免长 JSON 被默认上限截断。"""

from __future__ import annotations

from unittest.mock import MagicMock

from mcs.plugins.llm.deepseek_llm import DeepSeekLLMPlugin


def test_max_tokens_default_is_high():
    plugin = DeepSeekLLMPlugin({"api_key": "x"})
    assert plugin.max_tokens == 32768


def test_max_tokens_configurable():
    plugin = DeepSeekLLMPlugin({"api_key": "x", "max_tokens": 4096})
    assert plugin.max_tokens == 4096


def test_raw_call_passes_max_tokens():
    plugin = DeepSeekLLMPlugin({"api_key": "x", "max_tokens": 8192})
    fake = MagicMock()
    fake.chat.completions.create.return_value.choices = [
        MagicMock(message=MagicMock(content="ok"))
    ]
    plugin.client = fake

    out = plugin._raw_call("system", "user")

    assert out == "ok"
    _, kwargs = fake.chat.completions.create.call_args
    assert kwargs["max_tokens"] == 8192


def test_thinking_disabled_passes_extra_body():
    """thinking 配置非空时，透传到 extra_body（智谱 GLM 关思维链）。"""
    plugin = DeepSeekLLMPlugin({"api_key": "x", "thinking": {"type": "disabled"}})
    fake = MagicMock()
    fake.chat.completions.create.return_value.choices = [
        MagicMock(message=MagicMock(content="ok"))
    ]
    plugin.client = fake

    plugin._raw_call("system", "user")

    _, kwargs = fake.chat.completions.create.call_args
    assert kwargs["extra_body"] == {"thinking": {"type": "disabled"}}


def test_no_thinking_omits_extra_body():
    """默认不配 thinking 时，不传 extra_body（向后兼容，不影响 deepseek 基线）。"""
    plugin = DeepSeekLLMPlugin({"api_key": "x"})
    fake = MagicMock()
    fake.chat.completions.create.return_value.choices = [
        MagicMock(message=MagicMock(content="ok"))
    ]
    plugin.client = fake

    plugin._raw_call("system", "user")

    _, kwargs = fake.chat.completions.create.call_args
    assert "extra_body" not in kwargs


def test_empty_thinking_omits_extra_body():
    """边界：thinking 为空 dict 视为未设，不传 extra_body（防空壳透传）。"""
    plugin = DeepSeekLLMPlugin({"api_key": "x", "thinking": {}})
    fake = MagicMock()
    fake.chat.completions.create.return_value.choices = [
        MagicMock(message=MagicMock(content="ok"))
    ]
    plugin.client = fake

    plugin._raw_call("system", "user")

    _, kwargs = fake.chat.completions.create.call_args
    assert "extra_body" not in kwargs

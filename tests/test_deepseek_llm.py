"""DeepSeek 插件回归：_raw_call 必须传 max_tokens，避免长 JSON 被默认上限截断。"""

from __future__ import annotations

from unittest.mock import MagicMock

from mcs.plugins.llm.deepseek_llm import DeepSeekLLMPlugin


def test_max_tokens_default_is_high():
    plugin = DeepSeekLLMPlugin({"api_key": "x"})
    assert plugin.max_tokens == 8192


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

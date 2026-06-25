"""ClaudeLLMPlugin.count_tokens 单测（mock Anthropic API + 降级场景）。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

from mcs.plugins.llm.claude_llm import ClaudeLLMPlugin


class TestClaudeCountTokens:
    """ClaudeLLMPlugin.count_tokens 走父类校准经验式（claude 族）。

    运行时不调 Anthropic count_tokens API——API 作为 TokenBudget 全域 counter 时
    会产生 O(邻域) 次网络调用且 429 降级破坏口径一致性，故仅用于 bench/calibration
    离线校准。运行时用确定性本地校准式（claude 族 ×1.7/÷3）。
    """

    def test_uses_claude_family_coefficient(self):
        """claude 族系数：CJK ×1.7。"""
        plugin = ClaudeLLMPlugin({"model": "claude-3-5-sonnet-latest"})
        assert plugin.count_tokens("深度学习") == int(4 * 1.7)  # 4 CJK → 6

    def test_does_not_call_api(self):
        """运行时不调 Anthropic count_tokens API（client 存在也不调）。"""
        plugin = ClaudeLLMPlugin({"model": "claude-3-5-sonnet-latest"})
        mock_client = MagicMock()
        plugin.client = mock_client
        plugin.count_tokens("some text")
        mock_client.messages.count_tokens.assert_not_called()

    def test_empty_text_returns_zero(self):
        """空文本返回 0。"""
        plugin = ClaudeLLMPlugin({"model": "claude-3-5-sonnet-latest"})
        assert plugin.count_tokens("") == 0


class TestClaudeContextWindowSize:
    """ClaudeLLMPlugin.context_window_size。"""

    def test_known_model(self):
        plugin = ClaudeLLMPlugin({"model": "claude-3-5-sonnet-latest"})
        assert plugin.context_window_size == 200_000

    def test_another_known_model(self):
        plugin = ClaudeLLMPlugin({"model": "claude-3-opus-20240229"})
        assert plugin.context_window_size == 200_000

    def test_unlisted_model_returns_default(self):
        """未列入映射表的 claude 模型回退默认窗口（前缀匹配已移除）。"""
        plugin = ClaudeLLMPlugin({"model": "claude-3-5-sonnet"})  # 不在精确表
        assert plugin.context_window_size == 200_000

    def test_unknown_model_returns_default(self):
        plugin = ClaudeLLMPlugin({"model": "claude-future-model"})
        assert plugin.context_window_size == 200_000

    def test_empty_model_returns_default(self):
        plugin = ClaudeLLMPlugin({"model": ""})
        assert plugin.context_window_size == 200_000

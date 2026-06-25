"""DeepSeekLLMPlugin.count_tokens 单测（tiktoken + 降级场景）。"""

from __future__ import annotations

from unittest.mock import patch

from mcs.plugins.llm.deepseek_llm import DeepSeekLLMPlugin


class TestDeepSeekCountTokens:
    """DeepSeekLLMPlugin.count_tokens。"""

    def test_tiktoken_returns_token_count(self):
        """tiktoken 正常时返回精确计数。"""
        plugin = DeepSeekLLMPlugin({"model": "deepseek-chat"})
        result = plugin.count_tokens("hello world")
        # tiktoken cl100k_base 对 "hello world" 的编码结果
        import tiktoken

        enc = tiktoken.get_encoding("cl100k_base")
        expected = len(enc.encode("hello world"))
        assert result == expected

    def test_tiktoken_chinese_text(self):
        """tiktoken 对中文文本的计数。"""
        plugin = DeepSeekLLMPlugin({"model": "deepseek-chat"})
        result = plugin.count_tokens("深度学习")
        assert result > 0
        # tiktoken 对中文的计数应高于旧经验式（CJK 1:1）
        # 但低于 claude 族校准经验式（CJK ×1.7）

    def test_tiktoken_failure_falls_back(self):
        """tiktoken 导入失败时降级到校准经验式。"""
        plugin = DeepSeekLLMPlugin({"model": "deepseek-chat"})
        # tiktoken 在 count_tokens 内延迟导入，patch tiktoken.get_encoding
        with patch("tiktoken.get_encoding", side_effect=ImportError("no tiktoken")):
            result = plugin.count_tokens("深度学习")
            # deepseek 族：4 CJK × 1.3 = 5
            assert result == int(4 * 1.3)

    def test_empty_text_returns_zero(self):
        plugin = DeepSeekLLMPlugin({"model": "deepseek-chat"})
        assert plugin.count_tokens("") == 0


class TestDeepSeekContextWindowSize:
    """DeepSeekLLMPlugin.context_window_size。"""

    def test_deepseek_chat(self):
        plugin = DeepSeekLLMPlugin({"model": "deepseek-chat"})
        assert plugin.context_window_size == 128_000

    def test_deepseek_reasoner(self):
        plugin = DeepSeekLLMPlugin({"model": "deepseek-reasoner"})
        assert plugin.context_window_size == 128_000

    def test_unknown_model_returns_default(self):
        plugin = DeepSeekLLMPlugin({"model": "deepseek-v2"})
        assert plugin.context_window_size == 128_000

"""OllamaLLMPlugin.count_tokens 单测（tiktoken + 降级场景）。"""

from __future__ import annotations

from unittest.mock import patch

from mcs.plugins.llm.ollama_llm import OllamaLLMPlugin


class TestOllamaCountTokens:
    """OllamaLLMPlugin.count_tokens。"""

    def test_tiktoken_returns_token_count(self):
        """tiktoken 正常时返回精确计数。"""
        plugin = OllamaLLMPlugin({"model": "qwen3.5:9b"})
        result = plugin.count_tokens("hello world")
        import tiktoken

        enc = tiktoken.get_encoding("cl100k_base")
        expected = len(enc.encode("hello world"))
        assert result == expected

    def test_tiktoken_chinese_text(self):
        """tiktoken 对中文文本的计数。"""
        plugin = OllamaLLMPlugin({"model": "qwen3.5:9b"})
        result = plugin.count_tokens("深度学习")
        assert result > 0

    def test_tiktoken_failure_falls_back(self):
        """tiktoken 不可用时降级到 ollama 族校准经验式（×1.3）。"""
        plugin = OllamaLLMPlugin({"model": "qwen3.5:9b"})
        with patch("tiktoken.get_encoding", side_effect=ImportError("no tiktoken")):
            result = plugin.count_tokens("深度学习")
            # _detect_model_family override → "ollama" → 4 CJK × 1.3 = 5
            assert result == int(4 * 1.3)

    def test_empty_text_returns_zero(self):
        plugin = OllamaLLMPlugin({"model": "qwen3.5:9b"})
        assert plugin.count_tokens("") == 0


class TestOllamaContextWindowSize:
    """OllamaLLMPlugin.context_window_size。"""

    def test_default_uses_num_ctx(self):
        """默认使用 num_ctx 配置值。"""
        plugin = OllamaLLMPlugin({"model": "qwen3.5:9b"})
        assert plugin.context_window_size == 8192  # 默认 num_ctx

    def test_custom_num_ctx(self):
        """自定义 num_ctx 时 context_window_size 跟随。"""
        plugin = OllamaLLMPlugin({"model": "qwen3.5:9b", "num_ctx": 32768})
        assert plugin.context_window_size == 32768

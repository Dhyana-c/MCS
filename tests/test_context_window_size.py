"""context_window_size 综合单测——各插件映射表 + 前缀匹配 + 未知模型回退。"""

from __future__ import annotations

from mcs.plugins.llm.claude_llm import ClaudeLLMPlugin
from mcs.plugins.llm.deepseek_llm import DeepSeekLLMPlugin
from mcs.plugins.llm.ollama_llm import OllamaLLMPlugin


class TestContextWindowSizeAllPlugins:
    """各 LLM 插件的 context_window_size。"""

    # ── Claude ──────────────────────────────────────────────────────────────

    def test_claude_3_5_sonnet_latest(self):
        plugin = ClaudeLLMPlugin({"model": "claude-3-5-sonnet-latest"})
        assert plugin.context_window_size == 200_000

    def test_claude_3_opus(self):
        plugin = ClaudeLLMPlugin({"model": "claude-3-opus-20240229"})
        assert plugin.context_window_size == 200_000

    def test_claude_3_haiku(self):
        plugin = ClaudeLLMPlugin({"model": "claude-3-haiku-20240307"})
        assert plugin.context_window_size == 200_000

    def test_claude_3_5_haiku(self):
        plugin = ClaudeLLMPlugin({"model": "claude-3-5-haiku-latest"})
        assert plugin.context_window_size == 200_000

    def test_claude_unknown_model_default(self):
        plugin = ClaudeLLMPlugin({"model": "claude-4-nexus"})
        assert plugin.context_window_size == 200_000

    # ── DeepSeek ────────────────────────────────────────────────────────────

    def test_deepseek_chat(self):
        plugin = DeepSeekLLMPlugin({"model": "deepseek-chat"})
        assert plugin.context_window_size == 128_000

    def test_deepseek_reasoner(self):
        plugin = DeepSeekLLMPlugin({"model": "deepseek-reasoner"})
        assert plugin.context_window_size == 128_000

    def test_deepseek_unknown_model_default(self):
        plugin = DeepSeekLLMPlugin({"model": "deepseek-v2-lite"})
        assert plugin.context_window_size == 128_000

    # ── Ollama ──────────────────────────────────────────────────────────────

    def test_ollama_default_num_ctx(self):
        plugin = OllamaLLMPlugin({"model": "qwen3.5:9b"})
        assert plugin.context_window_size == 8192

    def test_ollama_custom_num_ctx(self):
        plugin = OllamaLLMPlugin({"model": "qwen3.5:9b", "num_ctx": 32768})
        assert plugin.context_window_size == 32768

    def test_ollama_empty_model(self):
        plugin = OllamaLLMPlugin({"model": ""})
        assert plugin.context_window_size == 8192

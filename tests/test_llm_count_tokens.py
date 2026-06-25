"""LLMInterface.count_tokens 默认实现单测。"""

from __future__ import annotations

from mcs.interfaces.llm import LLMInterface


class _StubLLM(LLMInterface):
    """测试用桩 LLM——只设 model 属性。"""

    def __init__(self, model: str = "unknown-model"):
        super().__init__({})
        self.model = model

    def get_name(self) -> str:
        return "stub_llm"

    def _raw_call(self, system: str, user: str) -> str:
        return ""


class TestCountTokensDefault:
    """LLMInterface.count_tokens 默认实现。"""

    def test_empty_string_returns_zero(self):
        llm = _StubLLM()
        assert llm.count_tokens("") == 0

    def test_none_returns_zero(self):
        llm = _StubLLM()
        assert llm.count_tokens(None) == 0

    def test_nonempty_returns_positive(self):
        llm = _StubLLM()
        assert llm.count_tokens("hello world") > 0

    def test_claude_model_uses_claude_family(self):
        """model 含 "claude" 时使用 claude 族系数。"""
        llm = _StubLLM(model="claude-3-5-sonnet-latest")
        # claude 族：CJK ×1.7, 非CJK ÷3
        text = "深度学习"  # 4 CJK chars
        result = llm.count_tokens(text)
        assert result == int(4 * 1.7)  # 6

    def test_deepseek_model_uses_deepseek_family(self):
        """model 含 "deepseek" 时使用 deepseek 族系数。"""
        llm = _StubLLM(model="deepseek-chat")
        text = "深度学习"  # 4 CJK chars
        result = llm.count_tokens(text)
        assert result == int(4 * 1.3)  # 5

    def test_gpt_model_uses_gpt_family(self):
        """model 含 "gpt" 时使用 gpt 族系数。"""
        llm = _StubLLM(model="gpt-4o")
        text = "深度学习"  # 4 CJK chars
        result = llm.count_tokens(text)
        assert result == int(4 * 1.7)  # 6

    def test_unknown_model_uses_conservative_coefficients(self):
        """未知模型使用保守系数（与 claude 相同）。"""
        llm = _StubLLM(model="some-random-model")
        text = "深度学习"  # 4 CJK chars
        result = llm.count_tokens(text)
        assert result == int(4 * 1.7)  # 6 — 保守高估


class TestDetectModelFamily:
    """_detect_model_family 辅助方法。"""

    def test_detect_claude(self):
        llm = _StubLLM(model="claude-3-5-sonnet-latest")
        assert llm._detect_model_family() == "claude"

    def test_detect_gpt(self):
        llm = _StubLLM(model="gpt-4o")
        assert llm._detect_model_family() == "gpt"

    def test_detect_deepseek(self):
        llm = _StubLLM(model="deepseek-chat")
        assert llm._detect_model_family() == "deepseek"

    def test_detect_unknown(self):
        llm = _StubLLM(model="qwen-7b")
        assert llm._detect_model_family() == "unknown"

    def test_detect_case_insensitive(self):
        llm = _StubLLM(model="Claude-3-Opus")
        assert llm._detect_model_family() == "claude"

    def test_detect_no_model_attr(self):
        """无 model 属性时回退到 unknown。"""
        llm = _StubLLM()
        delattr(llm, "model")
        assert llm._detect_model_family() == "unknown"


class TestContextWindowDefault:
    """LLMInterface.context_window_size 默认值。"""

    def test_default_returns_16000(self):
        llm = _StubLLM()
        assert llm.context_window_size == 16_000

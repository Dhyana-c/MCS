"""CalibratedEstimator 单测——覆盖各模型族系数、空值、边界。"""

from __future__ import annotations

from mcs.core.calibrated_estimator import CalibratedEstimator


class TestCoefficients:
    """各模型族的系数正确性。"""

    def test_claude_cjk_coefficient(self):
        est = CalibratedEstimator("claude")
        assert est._cjk_coeff == 1.7
        assert est._non_cjk_divisor == 3

    def test_gpt_cjk_coefficient(self):
        est = CalibratedEstimator("gpt")
        assert est._cjk_coeff == 1.7
        assert est._non_cjk_divisor == 3

    def test_deepseek_cjk_coefficient(self):
        est = CalibratedEstimator("deepseek")
        assert est._cjk_coeff == 1.3
        assert est._non_cjk_divisor == 4

    def test_ollama_cjk_coefficient(self):
        est = CalibratedEstimator("ollama")
        assert est._cjk_coeff == 1.3
        assert est._non_cjk_divisor == 4

    def test_unknown_uses_conservative_coefficients(self):
        """unknown 模型族采用最保守系数（与 claude/gpt 相同）。"""
        est = CalibratedEstimator("unknown")
        assert est._cjk_coeff == 1.7
        assert est._non_cjk_divisor == 3

    def test_invalid_family_falls_back_to_unknown(self):
        """不在映射表中的模型族回退到 unknown。"""
        est = CalibratedEstimator("nonexistent_model")
        assert est._cjk_coeff == 1.7
        assert est._non_cjk_divisor == 3

    def test_default_family_is_unknown(self):
        est = CalibratedEstimator()
        assert est._cjk_coeff == 1.7
        assert est._non_cjk_divisor == 3


class TestEstimate:
    """估算逻辑正确性。"""

    def test_empty_string_returns_zero(self):
        est = CalibratedEstimator("claude")
        assert est.estimate("") == 0

    def test_none_returns_zero(self):
        est = CalibratedEstimator("claude")
        assert est.estimate(None) == 0

    def test_single_char_returns_at_least_one(self):
        est = CalibratedEstimator("claude")
        assert est.estimate("a") >= 1

    def test_pure_cjk_claude(self):
        """Claude 族中文估算：15 个 CJK 字 × 1.7 = 25.5 → 25。"""
        est = CalibratedEstimator("claude")
        text = "深度学习是机器学习的一个子领域"  # 15 CJK chars
        result = est.estimate(text)
        cjk = sum(1 for ch in text if "一" <= ch <= "鿿")
        assert cjk == 15
        assert result == int(cjk * 1.7)  # 25

    def test_pure_cjk_deepseek(self):
        """DeepSeek 族中文估算：15 个 CJK 字 × 1.3 = 19.5 → 19。"""
        est = CalibratedEstimator("deepseek")
        text = "深度学习是机器学习的一个子领域"  # 15 CJK chars
        result = est.estimate(text)
        cjk = sum(1 for ch in text if "一" <= ch <= "鿿")
        assert cjk == 15
        assert result == int(cjk * 1.3)  # 19

    def test_pure_english_claude(self):
        """Claude 族英文估算：60 字符 ÷ 3 = 20。"""
        est = CalibratedEstimator("claude")
        text = "This is a sample English text for testing token estimation."
        cjk = sum(1 for ch in text if "一" <= ch <= "鿿")
        non_cjk = len(text) - cjk
        result = est.estimate(text)
        assert result == max(1, int(cjk * 1.7 + non_cjk // 3))

    def test_pure_english_deepseek(self):
        """DeepSeek 族英文估算：60 字符 ÷ 4 = 15。"""
        est = CalibratedEstimator("deepseek")
        text = "This is a sample English text for testing token estimation."
        cjk = sum(1 for ch in text if "一" <= ch <= "鿿")
        non_cjk = len(text) - cjk
        result = est.estimate(text)
        assert result == max(1, int(cjk * 1.3 + non_cjk // 4))

    def test_mixed_text_claude(self):
        """中英混合文本的估算。"""
        est = CalibratedEstimator("claude")
        text = "GPT-4 是一个大语言模型"  # 8 CJK + 6 non-CJK ("GPT-4 ")
        cjk = sum(1 for ch in text if "一" <= ch <= "鿿")
        non_cjk = len(text) - cjk
        assert cjk == 8
        assert non_cjk == 6
        result = est.estimate(text)
        expected = max(1, int(cjk * 1.7 + non_cjk // 3))
        assert result == expected

    def test_claude_overestimates_cjk_vs_deepseek(self):
        """Claude 族对中文的估算高于 DeepSeek 族（保守策略）。"""
        text = "深度学习是机器学习的一个子领域"
        est_claude = CalibratedEstimator("claude")
        est_deepseek = CalibratedEstimator("deepseek")
        assert est_claude.estimate(text) > est_deepseek.estimate(text)

    def test_never_returns_zero_for_nonempty(self):
        """非空文本至少返回 1。"""
        for family in ["claude", "gpt", "deepseek", "ollama", "unknown"]:
            est = CalibratedEstimator(family)
            assert est.estimate("x") >= 1


class TestModelFamily:
    """model_family 属性正确性。"""

    def test_known_family(self):
        est = CalibratedEstimator("claude")
        assert est.model_family == "claude"

    def test_unknown_family(self):
        est = CalibratedEstimator("unknown")
        assert est.model_family == "unknown"

    def test_default_family(self):
        est = CalibratedEstimator()
        assert est.model_family == "unknown"

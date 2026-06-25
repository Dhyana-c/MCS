"""校准经验式 token 估算器——精确方案的兜底。

当 LLM 插件的精确计数（API / tiktoken）不可用时，使用按模型族调整系数的
经验式替代当前硬编码的 CJK 1:1 + 非CJK 4:1。

设计原则：宁可高估（过早触发裂变）也不低估（破坏核心不变量）。
unknown 模型采用 claude/gpt 系数（最保守）。

系数来源：下表系数为文献/经验值（CJK 系数取各模型族中文 token/字 的保守上界）。
``bench/calibration/calibrate_token_estimator.py`` 提供校准工具（对照精确计数拟合
系数），尚未跑实测定标；定标后更新 ``COEFFICIENTS``。
"""

from __future__ import annotations


class CalibratedEstimator:
    """按模型族调整系数的经验式 token 估算器。

    每个模型族有独立的 CJK 系数和非 CJK 除数：

        estimate(text) = cjk_count * cjk_coeff + non_cjk_count // non_cjk_divisor

    系数表为文献/经验值（详见 design.md §校准方法论），待 bench/calibration 实测定标。
    """

    # 模型族 → (CJK 系数, 非CJK 字符/token 除数)。文献/经验值，待实测定标
    COEFFICIENTS: dict[str, tuple[float, int]] = {
        "claude": (1.7, 3),
        "gpt": (1.7, 3),
        "deepseek": (1.3, 4),
        "ollama": (1.3, 4),
        "unknown": (1.7, 3),  # 保守——与 claude/gpt 相同
    }

    def __init__(self, model_family: str = "unknown") -> None:
        self._model_family = model_family
        cjk_coeff, non_cjk_divisor = self.COEFFICIENTS.get(
            model_family, self.COEFFICIENTS["unknown"]
        )
        self._cjk_coeff = cjk_coeff
        self._non_cjk_divisor = non_cjk_divisor

    @property
    def model_family(self) -> str:
        """返回构造时指定的模型族名称。"""
        return self._model_family

    def estimate(self, text: str | None) -> int:
        """估算 ``text`` 的 token 数量。

        - CJK 字符按 ``cjk_coeff`` 计（如 claude ×1.7）
        - 非 CJK 字符按 ``non_cjk_divisor`` 除（如 claude ÷3）
        - 空值/None 返回 0
        - 非空文本至少返回 1
        """
        if not text:
            return 0
        cjk = sum(1 for ch in text if "一" <= ch <= "鿿")
        non_cjk = len(text) - cjk
        return max(1, int(cjk * self._cjk_coeff + non_cjk // self._non_cjk_divisor))

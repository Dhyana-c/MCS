"""TokenBudget 估计测试。覆盖 subgraph-bounding tasks 1.1–1.3。"""

from __future__ import annotations

from mcs.core.token_budget import TokenBudget


def test_estimate_english_not_overestimated():
    b = TokenBudget(8000)
    s = "Tesla Model 3 production ramps up in Shanghai gigafactory"  # 56 字符
    est = b.estimate(s)
    # 旧 len//2 = 28（高估约 2×）；新估应明显更低、接近真实 token 量级
    assert est < len(s) // 2
    assert est >= len(s.split())  # 不低于词数量级


def test_estimate_cjk_reasonable():
    b = TokenBudget(8000)
    s = "深度学习是机器学习的一个子领域"  # 14 个 CJK 字
    est = b.estimate(s)
    assert est >= 10  # CJK ~1 token/字，不被低估


def test_estimate_empty_and_none():
    b = TokenBudget(8000)
    assert b.estimate("") == 0
    assert b.estimate(None) == 0


def test_estimate_uses_injected_counter():
    b = TokenBudget(8000, counter=lambda t: 999)
    assert b.estimate("anything") == 999


def test_estimate_counter_failure_falls_back():
    def bad(_t):
        raise ValueError("boom")

    b = TokenBudget(8000, counter=bad)
    assert b.estimate("hello world") > 0  # 注入器异常 → 回退经验式，不报错

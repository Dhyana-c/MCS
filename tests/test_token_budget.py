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


# ─── Task 1.3: 口径统一单测（估算 == 渲染）────────────────────────────────────────


def test_estimate_node_matches_rendering():
    """估算值 == 完整渲染文本的 token 量（同口径断言）。

    estimate_node 使用 render_node_full（含格式行、body），与实际渲染一致。
    """
    from mcs.core.context_renderer import ContextRenderer
    from mcs.entities.graph import Node

    b = TokenBudget(8000)
    # name == content：去重，只计一份
    n1 = Node(id="a", name="Fantasy Football", content="Fantasy Football")
    rendered1 = ContextRenderer.render_node_full(
        n1, purpose="decide_hub", is_focus=True, extensions=None
    )
    estimated1 = b.estimate_node(n1)
    assert estimated1 == b.estimate(rendered1)

    # name != content：计两份
    n2 = Node(id="b", name="AI", content="Artificial Intelligence")
    rendered2 = ContextRenderer.render_node_full(
        n2, purpose="decide_hub", is_focus=True, extensions=None
    )
    estimated2 = b.estimate_node(n2)
    assert estimated2 == b.estimate(rendered2)


def test_estimate_node_deduplication_saves_tokens():
    """name==content 去重比 name!=content 省 token（隔离 content 长度变量）。

    两节点正文长度相同，唯一差异是 name 是否等于 content：相等者去重只计一份，
    不相等者 name+content 都计——后者必然更大。
    """
    from mcs.entities.graph import Node

    b = TokenBudget(8000)
    text = "Some Long Concept Name That Would Be Counted Twice" * 10
    n_dedup = Node(id="a", name=text, content=text)  # name == content → 去重
    n_full = Node(id="b", name="distinct short name", content=text)  # 都写
    assert b.estimate_node(n_dedup) < b.estimate_node(n_full)


def test_check_subgraph_uses_node_estimate():
    """check_subgraph 使用 estimate_node（口径统一）。"""
    from mcs.entities.graph import Node

    b = TokenBudget(100)
    nodes = [Node(id=str(i), name=f"n{i}", content="x" * 50) for i in range(5)]
    # 每个 node 约 50/4 ≈ 12-13 token；5 个约 60-65 < 100
    assert b.check_subgraph(nodes) is True

    nodes.append(Node(id="big", name="big", content="y" * 400))
    # 加一个大节点后应超预算
    assert b.check_subgraph(nodes) is False

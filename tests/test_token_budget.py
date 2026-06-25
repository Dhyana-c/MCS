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
    assert b.estimate("hello world") > 0  # 注入器异常 → 回退保守校准式，不报错


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
    nodes = [Node(id=str(i), name=f"n{i}", content="x" * 20) for i in range(5)]
    # 无 counter → 保守校准式（非CJK ÷3）：每 node 约 11 token；5 个约 55 < 100
    assert b.check_subgraph(nodes) is True

    nodes.append(Node(id="big", name="big", content="y" * 400))
    # 加一个大节点（约 139 token）后应超预算
    assert b.check_subgraph(nodes) is False


# ─── W = S + T + R 预算划分 ───────────────────────────────────────────────


def test_default_R_equals_T():
    """默认 R = T（结果窗口等于查询窗口）。"""
    b = TokenBudget(8000)
    assert b.T == 8000
    assert b.R == 8000
    assert b.S == 0
    assert b.W == 16000  # S + T + R = 0 + 8000 + 8000


def test_custom_window_partition():
    """自定义窗口划分：W = S + T + R。"""
    b = TokenBudget(6000, system_window=2000, result_window=6000)
    assert b.T == 6000
    assert b.S == 2000
    assert b.R == 6000
    assert b.W == 14000  # 2000 + 6000 + 6000


def test_explicit_window_size():
    """显式指定 W（覆盖默认计算）。"""
    b = TokenBudget(8000, window_size=20000, system_window=4000, result_window=8000)
    assert b.W == 20000
    assert b.T == 8000
    assert b.S == 4000
    assert b.R == 8000


def test_backward_compatible_max_tokens():
    """旧代码 TokenBudget(8000) 仍然工作：T=8000, W=16000, R=8000。"""
    b = TokenBudget(8000)
    assert b.T == 8000
    assert b.W == b.S + b.T + b.R


# ─── 模型感知 token 计数注入 ────────────────────────────────────────────────


def test_estimate_uses_llm_counter_when_injected():
    """注入 LLM counter 后，estimate 使用精确计数替代经验式。"""
    import tiktoken

    enc = tiktoken.get_encoding("cl100k_base")
    b = TokenBudget(8000, counter=lambda t: len(enc.encode(t)))
    text = "深度学习是机器学习的一个子领域"
    result = b.estimate(text)
    # 用 tiktoken 精确计数验证
    expected = len(enc.encode(text))
    assert result == expected


def test_estimate_llm_counter_more_accurate_than_heuristic():
    """LLM counter 对中文的估算比无 counter 的保守校准式更接近真实值。"""
    import tiktoken

    enc = tiktoken.get_encoding("cl100k_base")
    text = "深度学习是机器学习的一个子领域"

    b_heuristic = TokenBudget(8000)  # 保守校准式（unknown ×1.7/÷3）
    b_new = TokenBudget(8000, counter=lambda t: len(enc.encode(t)))  # tiktoken

    heuristic_est = b_heuristic.estimate(text)
    new_est = b_new.estimate(text)
    true_val = len(enc.encode(text))

    # tiktoken counter 恒等于真实值（abs=0），保守校准式有偏差
    assert abs(new_est - true_val) < abs(heuristic_est - true_val)


def test_estimate_without_counter_still_works():
    """未注入 counter 时，回退保守校准式（unknown 族 ×1.7/÷3）。"""
    b = TokenBudget(8000)  # 无 counter
    text = "hello world"
    result = b.estimate(text)
    # 保守校准式：0 CJK×1.7 + 11 non-CJK // 3 = 3
    assert result == max(1, int(0 * 1.7 + 11 // 3))


def test_estimate_node_uses_injected_counter():
    """estimate_node 使用注入的 counter。"""
    import tiktoken

    from mcs.entities.graph import Node

    enc = tiktoken.get_encoding("cl100k_base")
    b = TokenBudget(8000, counter=lambda t: len(enc.encode(t)))
    node = Node(id="test", name="AI", content="Artificial Intelligence")
    result = b.estimate_node(node)
    assert result > 0
    # 验证与直接对渲染文本计数一致
    from mcs.core.context_renderer import ContextRenderer

    rendered = ContextRenderer.render_node_full(
        node, purpose="decide_hub", is_focus=True, extensions=None
    )
    assert result == b.estimate(rendered)

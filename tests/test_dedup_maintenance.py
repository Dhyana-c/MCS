"""去重维护插件测试。

覆盖 #34：去重/合并的读写触发路径 + 后台维护扫描。
"""

from __future__ import annotations

from mcs.core.token_budget import TokenBudget
from mcs.entities.graph import CLASS_CONCEPT, CLASS_EVENT, CLASS_FACT, CLASS_SOURCE, EDGE_ASSOC, Node
from mcs.plugins.maintenance.dedup_maintenance import DedupMaintenance
from mcs.stores.in_memory import InMemoryStore


def _store_with(*nodes: Node) -> InMemoryStore:
    store = InMemoryStore()
    for n in nodes:
        store.add_node(n)
    return store


class TestDedupMaintenance:

    def test_should_run_default_false(self):
        """should_run() 默认返回 False（外部调度控制）。"""
        assert DedupMaintenance().should_run() is False

    def test_merges_same_name_concepts(self):
        """同名概念节点合并：保留第一个，删除重复。"""
        store = _store_with(
            Node(id="a1", name="苹果", content="苹果公司", node_class=CLASS_CONCEPT),
            Node(id="a2", name="苹果", content="苹果水果", node_class=CLASS_CONCEPT),
        )
        DedupMaintenance().run(store)
        # 只剩一个
        remaining = [n for n in store.get_all_nodes() if n.name == "苹果"]
        assert len(remaining) == 1
        # content 包含两者
        assert "苹果公司" in remaining[0].content
        assert "苹果水果" in remaining[0].content

    def test_merges_same_name_facts(self):
        """同名事实节点合并。"""
        store = _store_with(
            Node(id="f1", name="地球是圆的", content="地球是圆的", node_class=CLASS_FACT),
            Node(id="f2", name="地球是圆的", content="地球是球形", node_class=CLASS_FACT),
        )
        DedupMaintenance().run(store)
        remaining = [n for n in store.get_all_nodes() if n.name == "地球是圆的"]
        assert len(remaining) == 1

    def test_skips_sources_and_events(self):
        """source/事件节点不合并。"""
        store = _store_with(
            Node(id="s1", name="log.txt", content="", node_class=CLASS_SOURCE),
            Node(id="s2", name="log.txt", content="data", node_class=CLASS_SOURCE),
        )
        DedupMaintenance().run(store)
        remaining = [n for n in store.get_all_nodes() if n.name == "log.txt"]
        assert len(remaining) == 2  # 不合并

    def test_no_merge_different_names(self):
        """不同名节点不合并。"""
        store = _store_with(
            Node(id="a", name="苹果", content="", node_class=CLASS_CONCEPT),
            Node(id="b", name="橙子", content="", node_class=CLASS_CONCEPT),
        )
        DedupMaintenance().run(store)
        assert len(store.get_all_nodes()) == 2

    def test_reroutes_edges_after_merge(self):
        """合并后，重复节点的关联边被重挂到目标节点。"""
        store = _store_with(
            Node(id="c", name="种子", content="", node_class=CLASS_CONCEPT),
            Node(id="a1", name="苹果", content="苹果公司", node_class=CLASS_CONCEPT),
            Node(id="a2", name="苹果", content="苹果水果", node_class=CLASS_CONCEPT),
        )
        store.add_edge("c", "a1")  # 种子 → 旧苹果1
        store.add_edge("c", "a2")  # 种子 → 旧苹果2
        DedupMaintenance().run(store)
        # a2 被删，a1 保留
        assert store.get_node("a2") is None
        # 种子 → a1 的边应仍在
        edges_to_a1 = [e for e in store.get_relations("c") if e.target_id == "a1"]
        assert len(edges_to_a1) >= 1

    def test_event_endorsement_preserved_after_merge(self):
        """P1-1：合并后事件背书边不丢失。

        载重规则使 get_relations 过滤事件边，但 delete_node 会删掉 事件→dup 的边。
        dedup 必须用 get_related_events 绕过载重规则重挂事件背书边。
        """
        store = _store_with(
            Node(id="f1", name="地球是平的", content="地球是平的", node_class=CLASS_FACT),
            Node(id="f2", name="地球是平的", content="古人认为地球是平的", node_class=CLASS_FACT),
            Node(id="e1", name="中世纪对话", content="用户说了地球是平的", node_class=CLASS_EVENT),
        )
        # 事件 → f2（背书）
        store.add_edge("e1", "f2", type=EDGE_ASSOC)

        # 合并前：f2 有事件背书
        events_before = store.get_related_events("f2")
        assert len(events_before) == 1

        DedupMaintenance().run(store)

        # f2 被删除，f1 保留
        assert store.get_node("f2") is None
        # 事件背书边应改挂到 f1（关键断言！）
        events_after = store.get_related_events("f1")
        assert len(events_after) >= 1
        assert any(e.id == "e1" for e in events_after)

    def test_content_substring_dedup(self):
        """content 子串去重：新 content 是已有 content 的子串时不追加。"""
        store = _store_with(
            Node(id="a1", name="AI", content="Artificial Intelligence is a field", node_class=CLASS_CONCEPT),
            Node(id="a2", name="AI", content="Intelligence", node_class=CLASS_CONCEPT),
        )
        DedupMaintenance().run(store)
        remaining = [n for n in store.get_all_nodes() if n.name == "AI"]
        assert len(remaining) == 1
        # "Intelligence" 是 "Artificial Intelligence is a field" 的子串 → 不追加
        assert "\n" not in remaining[0].content

    def test_noop_when_no_duplicates(self):
        """无同名节点时 run() 不做任何修改。"""
        store = _store_with(
            Node(id="a", name="概念A", content="", node_class=CLASS_CONCEPT),
            Node(id="b", name="概念B", content="", node_class=CLASS_CONCEPT),
        )
        before = len(store.get_all_nodes())
        DedupMaintenance().run(store)
        assert len(store.get_all_nodes()) == before

    def test_guard_skips_merge_when_over_T(self):
        """P2-3：合并后 target 超 T 时挂起（跳过该对，不合并）。"""
        store = _store_with(
            Node(id="a1", name="大概念", content="X" * 4000, node_class=CLASS_CONCEPT),
            Node(id="a2", name="大概念", content="Y" * 4000, node_class=CLASS_CONCEPT),
        )
        tb = TokenBudget(200)  # 极小预算
        DedupMaintenance(token_budget=tb).run(store)
        # 超 T → 不合并，两个都保留
        remaining = [n for n in store.get_all_nodes() if n.name == "大概念"]
        assert len(remaining) == 2

    def test_no_token_budget_always_merges(self):
        """无 token_budget 时不过守门（无预算信息），直接合并。"""
        store = _store_with(
            Node(id="a1", name="大概念", content="X" * 4000, node_class=CLASS_CONCEPT),
            Node(id="a2", name="大概念", content="Y" * 4000, node_class=CLASS_CONCEPT),
        )
        # 不传 token_budget → 不过守门
        DedupMaintenance().run(store)
        remaining = [n for n in store.get_all_nodes() if n.name == "大概念"]
        assert len(remaining) == 1

"""WritePipeline._apply_decisions 测试：3 种 action 类型 + 错误处理。"""

from __future__ import annotations

import pytest

from mcs.core.errors import InvalidDecisionError, UnknownActionError
from mcs.core.plugin_manager import PluginManager
from mcs.core.query_engine import QueryEngine
from mcs.core.store import StoreInterface
from mcs.core.token_budget import TokenBudget
from mcs.core.write_pipeline import WritePipeline
from mcs.entities.decisions import ConceptDraft, Decision
from mcs.entities.graph import CLASS_CONCEPT, CLASS_FACT, EDGE_MUTEX, Node


def _make_pipeline(store: StoreInterface, mock_llm) -> WritePipeline:
    pm = PluginManager()
    pm.register(mock_llm)
    tb = TokenBudget(8000)
    qe = QueryEngine(store=store, llm=mock_llm, plugin_manager=pm, token_budget=tb)
    return WritePipeline(
        store=store,
        llm=mock_llm,
        query_engine=qe,
        plugin_manager=pm,
        token_budget=tb,
    )


def test_create_adds_node_with_edges(empty_graph, mock_llm):
    a = Node(id="anchor1", name="A", content="")
    b = Node(id="anchor2", name="B", content="")
    empty_graph.add_node(a)
    empty_graph.add_node(b)

    wp = _make_pipeline(empty_graph, mock_llm)
    concept = ConceptDraft(name="新概念", content="新内容")
    changed = wp._apply_decisions(
        [
            Decision(
                action="create",
                concept=concept,
                edges_to=[
                    {"target_id": "anchor1"},
                    {"target_id": "anchor2"},
                ],
            )
        ]
    )
    assert len(changed) == 1
    new_node = changed[0]
    assert new_node.name == "新概念"
    # 两个锚点都应该是新节点的事实邻居（事实边两端可达）。
    fact_targets = {e.target_id for e in empty_graph.get_relations(new_node.id)}
    assert fact_targets == {"anchor1", "anchor2"}


def test_create_links_intra_batch_via_edges_to_names(empty_graph, mock_llm):
    """同一批新概念之间用 edges_to_names 按名互连（篇内关系边）。"""
    wp = _make_pipeline(empty_graph, mock_llm)
    changed = wp._apply_decisions(
        [
            Decision(
                action="create",
                concept=ConceptDraft(name="苹果公司", content=""),
                edges_to_names=[
                    {"target_name": "iPhone"},
                    {"target_name": "乔布斯"},
                ],
            ),
            Decision(action="create", concept=ConceptDraft(name="iPhone", content="")),
            Decision(action="create", concept=ConceptDraft(name="乔布斯", content="")),
        ]
    )
    assert [c.name for c in changed] == ["苹果公司", "iPhone", "乔布斯"]
    apple = next(n for n in empty_graph.get_all_nodes() if n.name == "苹果公司")
    fact_targets = {n.name for e in empty_graph.get_relations(apple.id)
                    for n in empty_graph.get_all_nodes()
                    if n.id == e.target_id}
    assert fact_targets == {"iPhone", "乔布斯"}


def test_edges_to_names_skips_unknown_and_self(empty_graph, mock_llm):
    """edges_to_names 引用未知名跳过、引用自身防自环。"""
    wp = _make_pipeline(empty_graph, mock_llm)
    wp._apply_decisions(
        [
            Decision(
                action="create",
                concept=ConceptDraft(name="A", content=""),
                edges_to_names=[
                    {"target_name": "A"},
                    {"target_name": "不存在"},
                    {"target_name": "B"},
                ],
            ),
            Decision(action="create", concept=ConceptDraft(name="B", content="")),
        ]
    )
    a = next(n for n in empty_graph.get_all_nodes() if n.name == "A")
    fact_targets = {n.name for e in empty_graph.get_relations(a.id)
                    for n in empty_graph.get_all_nodes()
                    if n.id == e.target_id}
    assert fact_targets == {"B"}


def test_edges_to_names_can_link_to_merged_target(empty_graph, mock_llm):
    """edges_to_names 指向一个被 merge 的概念名 → 连到其 merge 目标节点。"""
    target = Node(id="t1", name="深度学习", content="")
    empty_graph.add_node(target)
    wp = _make_pipeline(empty_graph, mock_llm)
    wp._apply_decisions(
        [
            Decision(
                action="merge",
                concept=ConceptDraft(name="DL", content=""),
                target_id="t1",
            ),
            Decision(
                action="create",
                concept=ConceptDraft(name="神经网络", content=""),
                edges_to_names=[{"target_name": "DL"}],
            ),
        ]
    )
    nn = next(n for n in empty_graph.get_all_nodes() if n.name == "神经网络")
    fact_targets = {e.target_id for e in empty_graph.get_relations(nn.id)}
    assert "t1" in fact_targets


def test_merge_does_not_add_node(empty_graph, mock_llm):
    target = Node(id="t1", name="Target", content="")
    empty_graph.add_node(target)
    before = len(empty_graph.get_all_nodes())

    wp = _make_pipeline(empty_graph, mock_llm)
    wp._apply_decisions(
        [
            Decision(
                action="merge",
                concept=ConceptDraft(name="newalias", content=""),
                target_id="t1",
            )
        ]
    )
    assert len(empty_graph.get_all_nodes()) == before


def test_merge_adds_aliases_to_target(empty_graph, mock_llm):
    """merge 必须把 aliases_to_add 与 concept.name 真正并入目标别名槽。"""
    target = Node(
        id="t1", name="深度学习", content="", extensions={"alias_index": {"aliases": []}}
    )
    empty_graph.add_node(target)

    wp = _make_pipeline(empty_graph, mock_llm)
    wp._apply_decisions(
        [
            Decision(
                action="merge",
                concept=ConceptDraft(name="deep learning", content=""),
                target_id="t1",
                aliases_to_add=["DL"],
            )
        ]
    )
    aliases = empty_graph.get_node("t1").extensions["alias_index"]["aliases"]
    assert "DL" in aliases
    assert "deep learning" in aliases
    # 不应把等于节点名本身的项当作别名重复写入
    assert "深度学习" not in aliases


def test_merge_appends_concept_content(empty_graph, mock_llm):
    """merge 时 concept.content 应追加到目标节点的 content（子串去重）。"""
    target = Node(id="t1", name="目标", content="已有内容")
    empty_graph.add_node(target)

    wp = _make_pipeline(empty_graph, mock_llm)
    wp._apply_decisions(
        [
            Decision(
                action="merge",
                concept=ConceptDraft(name="x", content="新增事实"),
                target_id="t1",
            )
        ]
    )
    merged = empty_graph.get_node("t1")
    assert "已有内容" in merged.content
    assert "新增事实" in merged.content


def test_merge_without_target_id_raises(empty_graph, mock_llm):
    wp = _make_pipeline(empty_graph, mock_llm)
    with pytest.raises(InvalidDecisionError):
        wp._apply_decisions(
            [
                Decision(
                    action="merge",
                    concept=ConceptDraft(name="X", content=""),
                    target_id=None,
                )
            ]
        )


def test_sanitize_drops_targetless_merge(empty_graph, mock_llm):
    """LLM 偶发的 target_id=null 的 merge 应被清洗丢弃，

    使整次摄入不再因单个坏决策崩溃；create 等正常决策保留。
    """
    wp = _make_pipeline(empty_graph, mock_llm)
    decisions = [
        Decision(
            action="merge",
            concept=ConceptDraft(name="X", content=""),
            target_id=None,
        ),
        Decision(action="create", concept=ConceptDraft(name="好", content="")),
    ]
    cleaned = wp._sanitize_decisions(decisions)
    assert [d.action for d in cleaned] == ["create"]
    # 清洗后应用不再抛 InvalidDecisionError
    changed = wp._apply_decisions(cleaned)
    assert len(changed) == 1
    assert changed[0].name == "好"


def test_no_op_changes_nothing(empty_graph, mock_llm):
    wp = _make_pipeline(empty_graph, mock_llm)
    changed = wp._apply_decisions(
        [Decision(action="no_op", reason="too vague")]
    )
    assert changed == []
    assert empty_graph.get_all_nodes() == []


def test_unknown_action_raises(empty_graph, mock_llm):
    wp = _make_pipeline(empty_graph, mock_llm)
    with pytest.raises(UnknownActionError):
        wp._apply_decisions(
            [Decision(action="delete_planet")]  # type: ignore[arg-type]
        )


def test_multiple_decisions_apply_in_order(empty_graph, mock_llm):
    wp = _make_pipeline(empty_graph, mock_llm)
    changed = wp._apply_decisions(
        [
            Decision(action="create", concept=ConceptDraft(name="A", content="")),
            Decision(action="create", concept=ConceptDraft(name="B", content="")),
            Decision(action="no_op"),
            Decision(action="create", concept=ConceptDraft(name="C", content="")),
        ]
    )
    assert [c.name for c in changed] == ["A", "B", "C"]
    assert len(empty_graph.get_all_nodes()) == 3


# ─── 事实节点 + 互斥边 ────────────────────────────────────────────────────


def test_create_fact_node(empty_graph, mock_llm):
    """Decision(node_class=事实) 创建 node_class=="事实" 的事实节点。"""
    wp = _make_pipeline(empty_graph, mock_llm)
    changed = wp._apply_decisions(
        [
            Decision(
                action="create",
                concept=ConceptDraft(name="苹果创立了NeXT", content="苹果创立了NeXT", node_class=CLASS_FACT),
                node_class=CLASS_FACT,
            )
        ]
    )
    assert len(changed) == 1
    assert changed[0].node_class == CLASS_FACT


def test_create_concept_node_default(empty_graph, mock_llm):
    """不设 node_class 时默认创建概念节点（向后兼容）。"""
    wp = _make_pipeline(empty_graph, mock_llm)
    changed = wp._apply_decisions(
        [Decision(action="create", concept=ConceptDraft(name="概念A", content=""))]
    )
    assert len(changed) == 1
    assert changed[0].node_class == CLASS_CONCEPT


def test_mutex_edge_created_between_facts(empty_graph, mock_llm):
    """Decision(mutex_with=[id]) 在两个事实间创建互斥边。"""
    fact1 = Node(id="f1", name="地球是平的", content="地球是平的", node_class=CLASS_FACT)
    empty_graph.add_node(fact1)

    wp = _make_pipeline(empty_graph, mock_llm)
    changed = wp._apply_decisions(
        [
            Decision(
                action="create",
                concept=ConceptDraft(name="地球是圆的", content="地球是圆的", node_class=CLASS_FACT),
                node_class=CLASS_FACT,
                mutex_with=["f1"],
            )
        ]
    )
    assert len(changed) == 1
    new_fact = changed[0]
    # 新事实 → f1 应有互斥边
    mutex_edges = [e for e in empty_graph.get_relations(new_fact.id) if e.type == EDGE_MUTEX]
    assert len(mutex_edges) >= 1
    # 互斥边的另一端应是 f1
    assert any(
        (e.source_id == "f1" or e.target_id == "f1") for e in mutex_edges
    )


def test_mutex_with_names_resolved_in_batch(empty_graph, mock_llm):
    """同批两个事实用 mutex_with_names 互连互斥边。"""
    wp = _make_pipeline(empty_graph, mock_llm)
    changed = wp._apply_decisions(
        [
            Decision(
                action="create",
                concept=ConceptDraft(name="事实A", content="A说法", node_class=CLASS_FACT),
                node_class=CLASS_FACT,
                mutex_with_names=["事实B"],
            ),
            Decision(
                action="create",
                concept=ConceptDraft(name="事实B", content="B说法", node_class=CLASS_FACT),
                node_class=CLASS_FACT,
                mutex_with_names=["事实A"],
            ),
        ]
    )
    assert len(changed) == 2
    fact_a = next(n for n in changed if n.name == "事实A")
    fact_b = next(n for n in changed if n.name == "事实B")
    # A→B 或 B→A 应有互斥边（store 层无序对去重，可能只一条）
    mutex = [e for e in empty_graph.get_relations(fact_a.id) if e.type == EDGE_MUTEX]
    assert len(mutex) >= 1


def test_concept_mutex_rejected(empty_graph, mock_llm):
    """概念间的 mutex_with 被拒绝——互斥边两端必须为事实（宪法"互斥恒为事实↔事实"）。

    store 层 add_edge(type=互斥) 校验两端 node_class==事实，概念间互斥抛 ValueError。
    _apply_decisions 中概念 mutex_with 应被静默跳过（不建边），而非让异常冒泡。
    """
    concept1 = Node(id="c1", name="苹果", content="", node_class=CLASS_CONCEPT)
    empty_graph.add_node(concept1)

    wp = _make_pipeline(empty_graph, mock_llm)
    changed = wp._apply_decisions(
        [
            Decision(
                action="create",
                concept=ConceptDraft(name="橙子", content=""),
                node_class=CLASS_CONCEPT,
                mutex_with=["c1"],
            )
        ]
    )
    assert len(changed) == 1
    # 概念间不建互斥边——store 层校验拒绝，_apply_decisions 中 add_edge 抛 ValueError
    # 应被静默跳过而非冒泡（概念 mutex_with 是 LLM 误判，不应崩管线）
    # 验证：概念节点无互斥边
    new_concept = changed[0]
    mutex_edges = [e for e in empty_graph.get_relations(new_concept.id) if e.type == EDGE_MUTEX]
    assert len(mutex_edges) == 0

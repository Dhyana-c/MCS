"""GraphSummaryPlugin 测试（graph-summary change，task 2.7）。

注入脚本化 mock ``llm_caller`` + ``InMemoryStore``（手建 root/hub 层级），不依赖真实 LLM。
覆盖：``should_run`` 边界、``run`` 归纳产出与正确 purpose/nodes_in/free_args、
``max_tokens`` 配置、异常隔离（保留旧摘要、不阻塞）、空图降级、非 str / 空返回不写 meta。
"""

from __future__ import annotations

from mcs.entities.graph import Node
from mcs.plugins.maintenance.graph_summary import GraphSummaryPlugin
from mcs.stores.in_memory import InMemoryStore

_SEED_ROOT = "__seed_root__"


def _store_with_hubs(*hubs: Node) -> InMemoryStore:
    store = InMemoryStore()
    store.add_node(Node(id=_SEED_ROOT, name=_SEED_ROOT, content="", role="hub"))
    for h in hubs:
        store.add_node(h)
        store.add_edge(_SEED_ROOT, h.id, kind="hierarchy")
    return store


def _concept(nid: str = "c1") -> Node:
    return Node(id=nid, name=nid, content="某概念", role="concept")


def _mock_llm(return_value="图主题摘要", raises: Exception | None = None):
    calls: list[tuple] = []

    def caller(purpose, nodes_in=None, free_args=None):
        calls.append(
            (purpose, [n.id for n in (nodes_in or [])], dict(free_args or {}))
        )
        if raises is not None:
            raise raises
        return return_value

    return caller, calls


# === should_run ===


def test_should_run_true_when_concept_present():
    assert GraphSummaryPlugin().should_run([_concept()], InMemoryStore()) is True


def test_should_run_false_when_no_concept():
    hub = Node(id="h1", name="h", content="", role="hub")
    assert GraphSummaryPlugin().should_run([hub], InMemoryStore()) is False


def test_should_run_false_when_empty():
    assert GraphSummaryPlugin().should_run([], InMemoryStore()) is False


# === run：归纳产出 ===


def test_run_summarizes_and_writes_meta():
    hub = Node(id="h1", name="机器学习", content="ML 基础", role="hub")
    store = _store_with_hubs(hub)
    caller, calls = _mock_llm("这张图关于机器学习基础")
    GraphSummaryPlugin().run([_concept()], store, caller)

    assert store.get_graph_meta("graph_summary") == "这张图关于机器学习基础"
    assert len(calls) == 1
    purpose, node_ids, free_args = calls[0]
    assert purpose == "gen_graph_summary"  # 图摘要专用 purpose（语义归纳 prompt）
    assert node_ids == ["h1"]  # 顶层 hub 作归纳输入
    assert free_args["max_tokens"] == 1000  # 默认预算


def test_run_max_tokens_config():
    hub = Node(id="h1", name="h", content="", role="hub")
    store = _store_with_hubs(hub)
    caller, calls = _mock_llm()
    GraphSummaryPlugin({"max_tokens": 500}).run([_concept()], store, caller)
    assert calls[0][2]["max_tokens"] == 500


# === run：异常隔离 ===


def test_run_llm_failure_isolated_keeps_old_summary():
    hub = Node(id="h1", name="h", content="", role="hub")
    store = _store_with_hubs(hub)
    store.set_graph_meta("graph_summary", "旧摘要")
    caller, _ = _mock_llm(raises=RuntimeError("llm down"))
    GraphSummaryPlugin().run([_concept()], store, caller)  # 不抛、不阻塞
    assert store.get_graph_meta("graph_summary") == "旧摘要"  # 旧摘要未被覆写


# === run：空图降级 ===


def test_run_empty_graph_no_call_no_raise():
    store = InMemoryStore()
    store.add_node(Node(id=_SEED_ROOT, name=_SEED_ROOT, content="", role="hub"))
    caller, calls = _mock_llm()
    GraphSummaryPlugin().run([_concept()], store, caller)  # 不抛
    assert calls == []  # root 无层级子 → 不调 llm
    assert store.get_graph_meta("graph_summary") is None


# === run：非 str / 空返回不写 meta ===


def test_run_non_string_return_not_written():
    hub = Node(id="h1", name="h", content="", role="hub")
    store = _store_with_hubs(hub)
    caller, _ = _mock_llm(return_value=123)
    GraphSummaryPlugin().run([_concept()], store, caller)
    assert store.get_graph_meta("graph_summary") is None


def test_run_empty_string_return_not_written():
    hub = Node(id="h1", name="h", content="", role="hub")
    store = _store_with_hubs(hub)
    caller, _ = _mock_llm(return_value="   ")
    GraphSummaryPlugin().run([_concept()], store, caller)
    assert store.get_graph_meta("graph_summary") is None

"""MemoryStore.graph_view 只读可视化原语测试（FakeMCS，不依赖真实 MCS / LLM）。

覆盖（对应 tasks 2.1–2.5）：根视图 / 节点不存在→None / 孤立叶子空；
property_graph 取 facts（带 label、端点入 nodes）；attribute_node 取 assoc
（无 label、属性节点入 nodes）；纯 dict 字段与 kind 取值 / nodes 按 id 去重 /
hierarchy 边契约；两模式关系边互斥；悬空关系边保留边但跳过端点；线程安全
（读方法经 _submit 单 worker 线程，执行线程 != 调用方）。
"""

from __future__ import annotations

import json
import threading

from mcs.entities.graph import Edge, Node
from mcs_agent.memory import MemoryStore


# === Fake store / query_engine / mcs（与 test_agent_memory 同构，本地隔离） ===


def _n(
    nid: str,
    name: str | None = None,
    role: str = "concept",
    content: str | None = None,
) -> Node:
    """构造 Node（content 默认=name）。"""
    nm = name if name is not None else nid
    return Node(id=nid, name=nm, content=content if content is not None else nm, role=role)


class FakeStore:
    """内存图：节点 dict + 三类边 list；读方法记录执行线程 id（线程安全断言用）。"""

    def __init__(self) -> None:
        self.nodes: dict[str, Node] = {}
        self.hierarchy: list[Edge] = []
        self.facts: list[Edge] = []
        self.assocs: list[Edge] = []
        self.read_threads: set[int] = set()

    def add_node(self, n: Node) -> None:
        self.nodes[n.id] = n

    def get_node(self, nid: str) -> Node | None:
        self.read_threads.add(threading.get_ident())
        return self.nodes.get(nid)

    def get_out_hierarchy(self, nid: str) -> list[Node]:
        self.read_threads.add(threading.get_ident())
        return [
            self.nodes[e.target_id]
            for e in self.hierarchy
            if e.source_id == nid and e.target_id in self.nodes
        ]

    def get_facts(self, nid: str, limit: int | None = None) -> list[Edge]:
        self.read_threads.add(threading.get_ident())
        es = [e for e in self.facts if e.source_id == nid or e.target_id == nid]
        return es[:limit] if limit else es

    def get_assoc(self, nid: str, limit: int | None = None) -> list[Edge]:
        self.read_threads.add(threading.get_ident())
        es = [e for e in self.assocs if e.source_id == nid or e.target_id == nid]
        return es[:limit] if limit else es


class FakeQueryEngine:
    def __init__(self, relation_model: str = "property_graph") -> None:
        self.relation_model = relation_model


class FakeMCS:
    def __init__(self, store: FakeStore, qe: FakeQueryEngine) -> None:
        self.store = store
        self.query_engine = qe


def _make(store: FakeStore, qe: FakeQueryEngine) -> MemoryStore:
    return MemoryStore(lambda: FakeMCS(store, qe))


# === 2.1 根视图 / 节点不存在 / 孤立叶子 ===


def test_root_view_focus_nodes_edges_relation_model():
    store = FakeStore()
    store.add_node(_n("__seed_root__", name="根", role="hub"))
    store.add_node(_n("c1", "概念甲"))
    store.add_node(_n("c2", "概念乙"))
    store.add_node(_n("f1", "事实端点"))
    store.hierarchy.append(Edge(source_id="__seed_root__", target_id="c1", kind="hierarchy"))
    store.hierarchy.append(Edge(source_id="__seed_root__", target_id="c2", kind="hierarchy"))
    store.facts.append(Edge(source_id="__seed_root__", target_id="f1", kind="fact", label="关联"))
    ms = _make(store, FakeQueryEngine("property_graph"))
    try:
        out = ms.graph_view("__seed_root__")
        assert out is not None
        assert out["node"]["id"] == "__seed_root__"
        assert out["node"]["role"] == "hub"
        assert out["relation_model"] == "property_graph"
        # 邻居 = 层级子 ∪ 关系端点
        assert {n["id"] for n in out["nodes"]} == {"c1", "c2", "f1"}
        kinds = [e["kind"] for e in out["edges"]]
        assert kinds.count("hierarchy") == 2
        assert kinds.count("fact") == 1
    finally:
        ms.shutdown()


def test_node_not_found_returns_none():
    ms = _make(FakeStore(), FakeQueryEngine())
    try:
        assert ms.graph_view("ghost") is None  # 不抛异常
    finally:
        ms.shutdown()


def test_isolated_leaf_empty_nodes_and_edges():
    store = FakeStore()
    store.add_node(_n("__seed_root__", role="hub"))
    store.add_node(_n("leaf"))
    store.hierarchy.append(Edge(source_id="__seed_root__", target_id="leaf", kind="hierarchy"))
    ms = _make(store, FakeQueryEngine())
    try:
        out = ms.graph_view("leaf")
        assert out is not None
        assert out["node"]["id"] == "leaf"
        assert out["nodes"] == []
        assert out["edges"] == []
    finally:
        ms.shutdown()


# === 2.2 property_graph 事实边（带 label、端点入 nodes；双向端点） ===


def test_property_graph_fact_edge_with_label_and_endpoint():
    store = FakeStore()
    store.add_node(_n("a"))
    store.add_node(_n("b"))
    store.facts.append(Edge(source_id="a", target_id="b", kind="fact", label="rel"))
    ms = _make(store, FakeQueryEngine("property_graph"))
    try:
        out = ms.graph_view("a")
        facts = [e for e in out["edges"] if e["kind"] == "fact"]
        assert len(facts) == 1
        assert facts[0]["label"] == "rel"  # 非空
        assert facts[0]["source"] == "a" and facts[0]["target"] == "b"
        assert "b" in {n["id"] for n in out["nodes"]}  # 另一端入 nodes
    finally:
        ms.shutdown()


def test_property_graph_fact_edge_reverse_endpoint():
    """焦点为 fact 边的宾，另一端（源）也应入 nodes。"""
    store = FakeStore()
    store.add_node(_n("a"))
    store.add_node(_n("b"))
    store.facts.append(Edge(source_id="a", target_id="b", kind="fact", label="causes"))
    ms = _make(store, FakeQueryEngine("property_graph"))
    try:
        out = ms.graph_view("b")
        facts = [e for e in out["edges"] if e["kind"] == "fact"]
        assert len(facts) == 1
        assert facts[0]["label"] == "causes"
        assert "a" in {n["id"] for n in out["nodes"]}  # 反查：另一端 a
    finally:
        ms.shutdown()


# === 2.3 attribute_node 关联边（无 label、属性节点入 nodes；两模式互斥） ===


def test_attribute_node_assoc_edge_no_label_attribute_endpoint():
    store = FakeStore()
    store.add_node(_n("c", role="concept"))
    store.add_node(_n("attr", role="attribute", content="某属性说法"))
    store.assocs.append(Edge(source_id="c", target_id="attr", kind="assoc", label=""))
    ms = _make(store, FakeQueryEngine("attribute_node"))
    try:
        out = ms.graph_view("c")
        assert out["relation_model"] == "attribute_node"
        assocs = [e for e in out["edges"] if e["kind"] == "assoc"]
        assert len(assocs) == 1
        assert assocs[0]["label"] == ""  # 无 label
        attr_nodes = [n for n in out["nodes"] if n["id"] == "attr"]
        assert len(attr_nodes) == 1
        assert attr_nodes[0]["role"] == "attribute"  # attribute 节点序列化进 nodes
    finally:
        ms.shutdown()


def test_property_graph_excludes_assoc_edges():
    store = FakeStore()
    store.add_node(_n("a"))
    store.add_node(_n("b"))
    store.facts.append(Edge(source_id="a", target_id="b", kind="fact", label="r"))
    store.assocs.append(Edge(source_id="a", target_id="b", kind="assoc", label=""))
    ms = _make(store, FakeQueryEngine("property_graph"))
    try:
        out = ms.graph_view("a")
        kinds = {e["kind"] for e in out["edges"]}
        assert "fact" in kinds
        assert "assoc" not in kinds  # property_graph 不取 assoc
    finally:
        ms.shutdown()


def test_attribute_node_excludes_fact_edges():
    store = FakeStore()
    store.add_node(_n("a"))
    store.add_node(_n("b"))
    store.facts.append(Edge(source_id="a", target_id="b", kind="fact", label="r"))
    store.assocs.append(Edge(source_id="a", target_id="b", kind="assoc", label=""))
    ms = _make(store, FakeQueryEngine("attribute_node"))
    try:
        out = ms.graph_view("a")
        kinds = {e["kind"] for e in out["edges"]}
        assert "assoc" in kinds
        assert "fact" not in kinds  # attribute_node 不取 fact
    finally:
        ms.shutdown()


# === 2.4 纯 dict 字段 / kind 取值 / 去重 / hierarchy 边契约 ===


def test_dict_fields_kinds_dedup_and_hierarchy_contract():
    store = FakeStore()
    store.add_node(_n("__seed_root__", role="hub"))
    store.add_node(_n("c1"))  # 既是层级子、又是 fact 端点（测去重）
    store.hierarchy.append(Edge(source_id="__seed_root__", target_id="c1", kind="hierarchy"))
    store.facts.append(Edge(source_id="__seed_root__", target_id="c1", kind="fact", label="r"))
    ms = _make(store, FakeQueryEngine("property_graph"))
    try:
        out = ms.graph_view("__seed_root__")
        # node / nodes[*] 恰四键
        assert set(out["node"].keys()) == {"id", "name", "content", "role"}
        for n in out["nodes"]:
            assert set(n.keys()) == {"id", "name", "content", "role"}
        # edges[*] 恰五键、kind 合法
        for e in out["edges"]:
            assert set(e.keys()) == {"id", "source", "target", "kind", "label"}
            assert e["kind"] in {"hierarchy", "fact", "assoc"}
        assert "relation_model" in out
        # nodes 按 id 去重：c1 既层级子又 fact 端点 → 只一份
        assert sum(1 for n in out["nodes"] if n["id"] == "c1") == 1
        # hierarchy 边契约
        hier = [e for e in out["edges"] if e["kind"] == "hierarchy"]
        assert len(hier) == 1
        assert hier[0]["source"] == "__seed_root__"
        assert hier[0]["target"] == "c1"
        assert hier[0]["label"] == ""
        # 纯 JSON 可序列化（不含 dataclass / 内部对象）
        json.dumps(out)
    finally:
        ms.shutdown()


# === 边界：悬空关系边（task 1.3） ===


def test_dangling_relation_edge_kept_without_endpoint():
    store = FakeStore()
    store.add_node(_n("a"))
    store.facts.append(Edge(source_id="a", target_id="ghost", kind="fact", label="r"))
    ms = _make(store, FakeQueryEngine("property_graph"))
    try:
        out = ms.graph_view("a")
        facts = [e for e in out["edges"] if e["kind"] == "fact"]
        assert len(facts) == 1  # 边仍保留
        assert facts[0]["target"] == "ghost"
        assert "ghost" not in {n["id"] for n in out["nodes"]}  # 悬空端点不崩、不入 nodes
        assert out["nodes"] == []
    finally:
        ms.shutdown()


# === 2.5 线程安全：读方法经单 worker 线程，执行线程 != 调用方 ===


def test_reads_run_in_single_worker_thread_not_caller():
    store = FakeStore()
    store.add_node(_n("__seed_root__", role="hub"))
    store.add_node(_n("c1"))
    store.hierarchy.append(Edge(source_id="__seed_root__", target_id="c1", kind="hierarchy"))
    ms = _make(store, FakeQueryEngine())
    try:
        ms.graph_view("__seed_root__")
        assert store.read_threads, "expected store read calls to be recorded"
        main_tid = threading.get_ident()
        for tid in store.read_threads:
            assert tid != main_tid, "store reads MUST run off the caller thread"
        assert len(store.read_threads) == 1  # 全部经同一个 worker 线程（max_workers=1）
    finally:
        ms.shutdown()

"""MemoryStore.graph_view 只读可视化原语测试（统一图模型，FakeMCS）。

覆盖：根视图 / 节点不存在→None / 孤立叶子空；关系边（关联/互斥）端点入 nodes；
纯 dict 字段（node_class/hub/type，无 kind/label/relation_model）/ nodes 按 id 去重 /
下钻关联边契约；悬空关系边保留边但跳过端点；线程安全（读经 _submit 单 worker 线程）。
"""

from __future__ import annotations

import json
import threading

from mcs.entities.graph import EDGE_ASSOC, EDGE_MUTEX, Edge, Node
from mcs_agent.memory import MemoryStore


# === Fake store / query_engine / mcs ===


def _n(
    nid: str,
    name: str | None = None,
    node_class: str = "概念",
    content: str | None = None,
    hub: bool = False,
) -> Node:
    """构造 Node（content 默认=name）。"""
    nm = name if name is not None else nid
    ext = {"hub": True} if hub else {}
    return Node(
        id=nid, name=nm, content=content if content is not None else nm,
        node_class=node_class, extensions=ext,
    )


class FakeStore:
    """内存图：节点 dict + 下钻边 + 关系边 list；读方法记录执行线程 id。"""

    def __init__(self) -> None:
        self.nodes: dict[str, Node] = {}
        self.hierarchy: list[Edge] = []   # 下钻成员（关联出边）
        self.relations: list[Edge] = []   # 关系边（关联 / 互斥）
        self.read_threads: set[int] = set()
        self.get_node_counts: dict[str, int] = {}

    def add_node(self, n: Node) -> None:
        self.nodes[n.id] = n

    def get_node(self, nid: str) -> Node | None:
        self.read_threads.add(threading.get_ident())
        self.get_node_counts[nid] = self.get_node_counts.get(nid, 0) + 1
        return self.nodes.get(nid)

    def get_out_hierarchy(self, nid: str) -> list[Node]:
        self.read_threads.add(threading.get_ident())
        return [
            self.nodes[e.target_id]
            for e in self.hierarchy
            if e.source_id == nid and e.target_id in self.nodes
        ]

    def get_relations(self, nid: str, limit: int | None = None) -> list[Edge]:
        self.read_threads.add(threading.get_ident())
        es = [e for e in self.relations if e.source_id == nid or e.target_id == nid]
        return es[:limit] if limit else es


class FakeQueryEngine:
    pass


class FakeMCS:
    def __init__(self, store: FakeStore, qe: FakeQueryEngine) -> None:
        self.store = store
        self.query_engine = qe
        self.read_manager = None


def _make(store: FakeStore, qe: FakeQueryEngine | None = None) -> MemoryStore:
    return MemoryStore(lambda: FakeMCS(store, qe or FakeQueryEngine()))


# === 根视图 / 节点不存在 / 孤立叶子 ===


def test_root_view_focus_nodes_edges():
    store = FakeStore()
    store.add_node(_n("__seed_root__", name="根", hub=True))
    store.add_node(_n("c1", "概念甲"))
    store.add_node(_n("c2", "概念乙"))
    store.add_node(_n("f1", "事实端点"))
    store.hierarchy.append(Edge(source_id="__seed_root__", target_id="c1", type=EDGE_ASSOC))
    store.hierarchy.append(Edge(source_id="__seed_root__", target_id="c2", type=EDGE_ASSOC))
    store.relations.append(Edge(source_id="__seed_root__", target_id="f1", type=EDGE_ASSOC))
    ms = _make(store)
    try:
        out = ms.graph_view("__seed_root__")
        assert out is not None
        assert out["node"]["id"] == "__seed_root__"
        assert out["node"]["hub"] is True
        assert "relation_model" not in out  # 统一模型已删
        # 邻居 = 下钻成员 ∪ 关系端点
        assert {n["id"] for n in out["nodes"]} == {"c1", "c2", "f1"}
        types = [e["type"] for e in out["edges"]]
        assert types.count("关联") == 3  # 2 下钻 + 1 关系
    finally:
        ms.shutdown()


def test_node_not_found_returns_none():
    ms = _make(FakeStore())
    try:
        assert ms.graph_view("ghost") is None  # 不抛异常
    finally:
        ms.shutdown()


def test_isolated_leaf_empty_nodes_and_edges():
    store = FakeStore()
    store.add_node(_n("__seed_root__", hub=True))
    store.add_node(_n("leaf"))
    store.hierarchy.append(Edge(source_id="__seed_root__", target_id="leaf", type=EDGE_ASSOC))
    ms = _make(store)
    try:
        out = ms.graph_view("leaf")
        assert out is not None
        assert out["node"]["id"] == "leaf"
        assert out["nodes"] == []
        assert out["edges"] == []
    finally:
        ms.shutdown()


# === 关系边（关联/互斥）端点入 nodes；双向端点 ===


def test_relation_edge_endpoint_in_nodes():
    store = FakeStore()
    store.add_node(_n("a"))
    store.add_node(_n("b"))
    store.relations.append(Edge(source_id="a", target_id="b", type=EDGE_ASSOC))
    ms = _make(store)
    try:
        out = ms.graph_view("a")
        rels = [e for e in out["edges"] if e["type"] == "关联"]
        assert len(rels) == 1
        assert rels[0]["source"] == "a" and rels[0]["target"] == "b"
        assert "b" in {n["id"] for n in out["nodes"]}  # 另一端入 nodes
    finally:
        ms.shutdown()


def test_relation_edge_reverse_endpoint():
    """焦点为关系边的宾，另一端（源）也应入 nodes（反查、双向可达）。"""
    store = FakeStore()
    store.add_node(_n("a"))
    store.add_node(_n("b"))
    store.relations.append(Edge(source_id="a", target_id="b", type=EDGE_MUTEX))
    ms = _make(store)
    try:
        out = ms.graph_view("b")
        rels = [e for e in out["edges"] if e["type"] == "互斥"]
        assert len(rels) == 1
        assert "a" in {n["id"] for n in out["nodes"]}  # 反查：另一端 a
    finally:
        ms.shutdown()


# === 纯 dict 字段 / type 取值 / 去重 / 下钻边契约 ===


def test_dict_fields_types_dedup_and_drill_contract():
    store = FakeStore()
    store.add_node(_n("__seed_root__", hub=True))
    store.add_node(_n("c1"))  # 既是下钻成员、又是关系端点（测去重）
    store.hierarchy.append(Edge(source_id="__seed_root__", target_id="c1", type=EDGE_ASSOC))
    store.relations.append(Edge(source_id="__seed_root__", target_id="c1", type=EDGE_ASSOC))
    ms = _make(store)
    try:
        out = ms.graph_view("__seed_root__")
        # node / nodes[*] 含六键（含 degree 热力度数）
        assert set(out["node"].keys()) == {"id", "name", "content", "node_class", "hub", "degree"}
        for n in out["nodes"]:
            assert set(n.keys()) == {"id", "name", "content", "node_class", "hub", "degree"}
        # degree = 下钻子数 + 关系边度数：root = 1 子 + 1 关系 = 2；c1 = 0 子 + 1 关系 = 1
        assert out["node"]["degree"] == 2
        c1 = next(n for n in out["nodes"] if n["id"] == "c1")
        assert c1["degree"] == 1
        # edges[*] 恰四键、type 合法
        for e in out["edges"]:
            assert set(e.keys()) == {"id", "source", "target", "type"}
            assert e["type"] in {"关联", "互斥"}
        assert "relation_model" not in out
        # nodes 按 id 去重：c1 既下钻成员又关系端点 → 只一份
        assert sum(1 for n in out["nodes"] if n["id"] == "c1") == 1
        # 下钻边契约（root→c1）
        drill = [e for e in out["edges"] if e["source"] == "__seed_root__" and e["target"] == "c1"]
        assert drill
        # 纯 JSON 可序列化（不含 dataclass / 内部对象）
        json.dumps(out)
    finally:
        ms.shutdown()


# === 边界：悬空关系边 ===


def test_dangling_relation_edge_kept_without_endpoint():
    store = FakeStore()
    store.add_node(_n("a"))
    store.relations.append(Edge(source_id="a", target_id="ghost", type=EDGE_ASSOC))
    ms = _make(store)
    try:
        out = ms.graph_view("a")
        rels = [e for e in out["edges"] if e["type"] == "关联"]
        assert len(rels) == 1  # 边仍保留
        assert rels[0]["target"] == "ghost"
        assert "ghost" not in {n["id"] for n in out["nodes"]}  # 悬空端点不崩、不入 nodes
        assert out["nodes"] == []
    finally:
        ms.shutdown()


def test_dangling_endpoint_queried_once_across_edges():
    """多条关系边指向同一悬空端点：get_node 对该端点只查一次（E1 去重），边仍全保留。"""
    store = FakeStore()
    store.add_node(_n("a"))
    # 三条关系边都指向不存在的 ghost（悬空）
    store.relations.append(Edge(source_id="a", target_id="ghost", type=EDGE_ASSOC))
    store.relations.append(Edge(source_id="a", target_id="ghost", type=EDGE_MUTEX))
    store.relations.append(Edge(source_id="ghost", target_id="a", type=EDGE_ASSOC))
    ms = _make(store)
    try:
        out = ms.graph_view("a")
        # 三条悬空边都保留进 edges
        assert len(out["edges"]) == 3
        # 但 ghost 端点只 get_node 一次（去重），不入 nodes
        assert store.get_node_counts.get("ghost", 0) == 1
        assert "ghost" not in {n["id"] for n in out["nodes"]}
    finally:
        ms.shutdown()


# === 线程安全：读方法经单 worker 线程，执行线程 != 调用方 ===


def test_reads_run_in_single_worker_thread_not_caller():
    store = FakeStore()
    store.add_node(_n("__seed_root__", hub=True))
    store.add_node(_n("c1"))
    store.hierarchy.append(Edge(source_id="__seed_root__", target_id="c1", type=EDGE_ASSOC))
    ms = _make(store)
    try:
        ms.graph_view("__seed_root__")
        assert store.read_threads, "expected store read calls to be recorded"
        main_tid = threading.get_ident()
        for tid in store.read_threads:
            assert tid != main_tid, "store reads MUST run off the caller thread"
        assert len(store.read_threads) == 1  # 全部经同一个 worker 线程（max_workers=1）
    finally:
        ms.shutdown()


# === node_class 值透传（非默认类）===


def test_node_class_value_passed_through():
    """graph_view 原样透传 node_class 值（事件/事实/source，不止 keys 存在）。

    现有断言只检 ``node_class`` 键存在；此处验证其**值**逐字透传，且非默认类
    （事件）节点无邻居时 nodes 空、不崩。载重规则不在此测——本文件用 FakeStore，
    其 ``get_relations`` 不做载重过滤；载重由真实 store 在
    ``test_unified_graph_schema.test_get_relations_*`` 覆盖。
    """
    store = FakeStore()
    store.add_node(_n("e", node_class="事件"))
    ms = _make(store)
    try:
        out = ms.graph_view("e")
        assert out is not None
        assert out["node"]["node_class"] == "事件"
        assert out["nodes"] == []  # 事件节点无邻居、不崩
    finally:
        ms.shutdown()

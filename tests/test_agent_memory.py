"""MemoryStore 5 原语测试：FakeMCS（带 store / query_engine），不依赖真实 MCS / LLM。

覆盖：search（keyword / direct / vector / 未知模式）、associate（mcs / hot / random /
seed 不存在）、find_path（连通 / 不连通 / 节点不存在 / 同节点 / 经事实边）、
recall（空壳）、learn（状态摘要）。另含 locate_seeds 委托等价性。
"""

from __future__ import annotations

from mcs.entities.graph import Edge, Node
from mcs_agent.memory import MemoryStore


# === Fake store / query_engine / mcs ===


def _n(nid: str, name: str | None = None) -> Node:
    """构造 Node（content 默认=name，测试不依赖 content 差异）。"""
    nm = name if name is not None else nid
    return Node(id=nid, name=nm, content=nm)


class FakeStore:
    """内存图：节点 dict + 三类边 list，实现路径搜索 / 种子所需接口。"""

    def __init__(self) -> None:
        self.nodes: dict[str, Node] = {}
        self.hierarchy: list[Edge] = []
        self.facts: list[Edge] = []
        self.assocs: list[Edge] = []

    def add_node(self, n: Node) -> None:
        self.nodes[n.id] = n

    def get_node(self, nid: str) -> Node | None:
        return self.nodes.get(nid)

    def get_out_hierarchy(self, nid: str) -> list[Node]:
        return [
            self.nodes[e.target_id]
            for e in self.hierarchy
            if e.source_id == nid and e.target_id in self.nodes
        ]

    def get_facts(self, nid: str, limit: int | None = None) -> list[Edge]:
        es = [e for e in self.facts if e.source_id == nid or e.target_id == nid]
        return es[:limit] if limit else es

    def get_assoc(self, nid: str, limit: int | None = None) -> list[Edge]:
        es = [e for e in self.assocs if e.source_id == nid or e.target_id == nid]
        return es[:limit] if limit else es


class FakeQueryEngine:
    relation_model = "property_graph"

    def __init__(self) -> None:
        self.locate_calls: list[str] = []
        self._seeds: list[Node] = []

    def set_seeds(self, seeds: list[Node]) -> None:
        self._seeds = list(seeds)

    def locate_seeds(self, query: str) -> list[Node]:
        self.locate_calls.append(query)
        return list(self._seeds)


class _FakeWriteCtx:
    changed = [1, 2]
    concepts = [1]
    persisted = True


class FakeMCS:
    def __init__(self, store: FakeStore, qe: FakeQueryEngine) -> None:
        self.store = store
        self.query_engine = qe
        self.read_manager = None
        self.last_query_existing_context: list | None = None

    def ingest(self, text: str) -> _FakeWriteCtx:
        return _FakeWriteCtx()

    def query(self, text: str, existing_context: list | None = None) -> str:
        self.last_query_existing_context = existing_context
        return f"raw-subgraph-for:{text}"

    def shutdown(self) -> None:
        pass


def _make(store: FakeStore, qe: FakeQueryEngine) -> tuple[MemoryStore, FakeMCS]:
    """构造 MemoryStore（build_fn 返回 FakeMCS）。"""
    mcs = FakeMCS(store, qe)
    return MemoryStore(lambda: mcs), mcs


def _line(store: FakeStore, ids: list[str]) -> None:
    """构造 id 顺序连成的层级链 a→b→c..."""
    for nid in ids:
        store.add_node(_n(nid))
    for a, b in zip(ids, ids[1:]):
        store.hierarchy.append(Edge(source_id=a, target_id=b, kind="hierarchy"))


# === search ===


def test_search_keyword():
    qe = FakeQueryEngine()
    qe.set_seeds([_n("c1", "猫")])
    ms, _ = _make(FakeStore(), qe)
    try:
        out = ms.search("猫", "keyword")
        assert "[id:c1]" in out
        assert qe.locate_calls == ["猫"]
    finally:
        ms.shutdown()


def test_search_direct_returns_root_children():
    store = FakeStore()
    for nid, nm in [("h1", "科学"), ("h2", "艺术")]:
        store.add_node(_n(nid, nm))
        store.hierarchy.append(
            Edge(source_id="__seed_root__", target_id=nid, kind="hierarchy")
        )
    qe = FakeQueryEngine()
    ms, _ = _make(store, qe)
    try:
        out = ms.search("anything", "direct")
        assert "[id:h1]" in out and "[id:h2]" in out
        assert qe.locate_calls == []  # direct 不走 locate_seeds
    finally:
        ms.shutdown()


def test_search_vector_unimplemented():
    ms, _ = _make(FakeStore(), FakeQueryEngine())
    try:
        assert "未实现" in ms.search("x", "vector")
    finally:
        ms.shutdown()


def test_search_unknown_mode():
    ms, _ = _make(FakeStore(), FakeQueryEngine())
    try:
        assert "error" in ms.search("x", "weird")
    finally:
        ms.shutdown()


# === associate ===


def test_associate_mcs_uses_existing_context():
    store = FakeStore()
    store.add_node(_n("c1", "种子"))
    ms, mcs = _make(store, FakeQueryEngine())
    try:
        out = ms.associate("c1", "mcs")
        assert mcs.last_query_existing_context is not None
        assert "种子" in str(mcs.last_query_existing_context)
        assert "raw-subgraph-for:" in out
    finally:
        ms.shutdown()


def test_associate_seed_missing():
    ms, _ = _make(FakeStore(), FakeQueryEngine())
    try:
        out = ms.associate("nope", "mcs")
        assert "error" in out and "不存在" in out
    finally:
        ms.shutdown()


def test_associate_hot_random_unimplemented():
    store = FakeStore()
    store.add_node(_n("c1", "x"))
    ms, _ = _make(store, FakeQueryEngine())
    try:
        assert "未实现" in ms.associate("c1", "hot")
        assert "未实现" in ms.associate("c1", "random")
    finally:
        ms.shutdown()


# === find_path ===


def test_find_path_connected():
    store = FakeStore()
    _line(store, ["a", "b", "c"])  # a→b→c
    ms, _ = _make(store, FakeQueryEngine())
    try:
        out = ms.find_path("a", "c")
        assert "找到路径" in out
        assert "[id:a]" in out and "[id:c]" in out
    finally:
        ms.shutdown()


def test_find_path_disconnected():
    store = FakeStore()
    _line(store, ["a", "b"])
    store.add_node(_n("z"))  # 孤立
    ms, _ = _make(store, FakeQueryEngine())
    try:
        assert "未找到" in ms.find_path("a", "z")
    finally:
        ms.shutdown()


def test_find_path_node_missing():
    store = FakeStore()
    store.add_node(_n("a"))
    ms, _ = _make(store, FakeQueryEngine())
    try:
        assert "不存在" in ms.find_path("a", "ghost")
        assert "不存在" in ms.find_path("ghost", "a")
    finally:
        ms.shutdown()


def test_find_path_same_node():
    store = FakeStore()
    store.add_node(_n("a"))
    ms, _ = _make(store, FakeQueryEngine())
    try:
        assert "[id:a]" in ms.find_path("a", "a")
    finally:
        ms.shutdown()


def test_find_path_via_fact_edge():
    """事实边端点也作为邻居（无向可达）。"""
    store = FakeStore()
    store.add_node(_n("a"))
    store.add_node(_n("b"))
    store.facts.append(Edge(source_id="a", target_id="b", kind="fact", label="related"))
    ms, _ = _make(store, FakeQueryEngine())
    try:
        assert "找到路径" in ms.find_path("a", "b")
    finally:
        ms.shutdown()


# === recall ===


def test_recall_unimplemented():
    ms, _ = _make(FakeStore(), FakeQueryEngine())
    try:
        assert "未实现" in ms.recall(5)
    finally:
        ms.shutdown()


# === learn ===


def test_learn_status():
    ms, _ = _make(FakeStore(), FakeQueryEngine())
    try:
        out = ms.learn("一段记忆")
        assert "已写入" in out
        assert "persisted=yes" in out
    finally:
        ms.shutdown()


# === locate_seeds 委托等价性（QueryEngine 公共薄方法不改 query 行为） ===


def test_locate_seeds_delegates_preprocess_then_locate():
    """locate_seeds 把 query 经 _run_preprocess 后传给 _locate_seeds（与 query() 内一致）。"""
    from mcs.core.query_engine import QueryEngine

    qe = QueryEngine.__new__(QueryEngine)  # 绕过 __init__，避免组装真依赖
    qe.system_prompt = ""
    calls: dict[str, str] = {}

    def fake_preprocess(text: str, ctx):
        calls["preprocess"] = text
        return text + "_proc"

    def fake_locate(processed: str, ctx):
        calls["locate"] = processed
        return [_n("x")]

    qe._run_preprocess = fake_preprocess  # type: ignore[method-assign]
    qe._locate_seeds = fake_locate  # type: ignore[method-assign]

    result = qe.locate_seeds("hello")
    assert calls == {"preprocess": "hello", "locate": "hello_proc"}
    assert [n.id for n in result] == ["x"]

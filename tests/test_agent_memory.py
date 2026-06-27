"""MemoryStore 5 原语测试：FakeMCS（带 store / query_engine），不依赖真实 MCS / LLM。

覆盖：search（keyword / direct / vector / 未知模式）、associate（mcs / hot / random /
seed 不存在）、find_path（连通 / 不连通 / 节点不存在 / 同节点 / 经事实边）、
recall（时间倒排 / limit·T 双截断 / 单条超 T / 空图 / 无 timestamp / 确定性次序）、
learn（状态摘要）。另含 locate_seeds 委托等价性。
"""

from __future__ import annotations

from mcs.core.token_budget import TokenBudget
from mcs.entities.graph import CLASS_EVENT, Edge, Node
from mcs_agent.memory import (
    MemoryStore,
    _RECALL_HEADER,
    _event_timestamp,
    _render_events,
)


# === Fake store / query_engine / mcs ===


def _n(nid: str, name: str | None = None) -> Node:
    """构造 Node（content 默认=name，测试不依赖 content 差异）。"""
    nm = name if name is not None else nid
    return Node(id=nid, name=nm, content=nm)


def _ev(
    nid: str, content: str, ts: str | None = None, name: str | None = None
) -> Node:
    """构造事件节点（node_class=事件，可选 event_meta.timestamp）。"""
    nm = name if name is not None else content
    ext: dict = {}
    if ts is not None:
        ext["event_meta"] = {"timestamp": ts}
    return Node(
        id=nid, name=nm, content=content, node_class=CLASS_EVENT, extensions=ext
    )


class FakeStore:
    """内存图：节点 dict + 三类边 list，实现路径搜索 / 种子所需接口。"""

    def __init__(self) -> None:
        self.nodes: dict[str, Node] = {}
        self.hierarchy: list[Edge] = []
        self.facts: list[Edge] = []
        self.assocs: list[Edge] = []
        self.graph_meta: dict[str, str] = {}

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

    def get_relations(self, nid: str, limit: int | None = None) -> list[Edge]:
        es = [e for e in (self.facts + self.assocs)
              if e.source_id == nid or e.target_id == nid]
        return es[:limit] if limit else es

    def get_graph_meta(self, key: str) -> str | None:
        return self.graph_meta.get(key)

    def get_all_nodes(self) -> list[Node]:
        return list(self.nodes.values())


class FakeQueryEngine:
    def __init__(self, token_budget_T: int = 8000) -> None:
        self.locate_calls: list[str] = []
        self._seeds: list[Node] = []
        # recall 经 query_engine.token_budget 取 T + estimate（只读消费、不动框架层）
        self.token_budget = TokenBudget(max_tokens=token_budget_T)

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
        store.hierarchy.append(Edge(source_id=a, target_id=b, type="关联"))


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
            Edge(source_id="__seed_root__", target_id=nid, type="关联")
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
    store.facts.append(Edge(source_id="a", target_id="b"))
    ms, _ = _make(store, FakeQueryEngine())
    try:
        assert "找到路径" in ms.find_path("a", "b")
    finally:
        ms.shutdown()


# === recall ===


def test_recall_recent_events():
    """时间倒排返回最近事件，渲染含 id 与 timestamp；非事件节点被过滤。"""
    store = FakeStore()
    store.add_node(_ev("e1", "买了咖啡", ts="2026-06-25T10:00:00+00:00"))
    store.add_node(_ev("e3", "看了电影", ts="2026-06-27T10:00:00+00:00"))
    store.add_node(_ev("e2", "写了代码", ts="2026-06-26T10:00:00+00:00"))
    store.add_node(_n("c1", "纯概念"))  # 非事件，必须被过滤
    ms, _ = _make(store, FakeQueryEngine())
    try:
        out = ms.recall(5)
        # 时间倒排：e3 > e2 > e1
        assert out.index("[id:e3]") < out.index("[id:e2]") < out.index("[id:e1]")
        # 含 id 与 timestamp
        assert "[id:e3]" in out and "2026-06-27" in out
        # 非事件节点不出现
        assert "[id:c1]" not in out
    finally:
        ms.shutdown()


def test_recall_empty_no_events():
    """图中无事件节点 → 空提示，不伪造。"""
    store = FakeStore()
    store.add_node(_n("c1", "只是概念"))
    ms, _ = _make(store, FakeQueryEngine())
    try:
        out = ms.recall(5)
        assert "暂无事件" in out
        assert "[id:c1]" not in out
    finally:
        ms.shutdown()


def test_recall_limit_truncation():
    """事件数 > limit → 仅返回最近 limit 条。"""
    store = FakeStore()
    for i in range(5):
        store.add_node(_ev(f"e{i}", f"事件{i}", ts=f"2026-06-2{i}T00:00:00+00:00"))
    ms, _ = _make(store, FakeQueryEngine())
    try:
        out = ms.recall(2)
        assert "[id:e4]" in out and "[id:e3]" in out  # 最近 2 条
        assert "[id:e2]" not in out and "[id:e0]" not in out
    finally:
        ms.shutdown()


def test_recall_no_timestamp_sorts_last():
    """无 timestamp 的事件排在有 timestamp 的之后（末尾）。"""
    store = FakeStore()
    store.add_node(_ev("e1", "有时间", ts="2026-06-26T00:00:00+00:00"))
    store.add_node(_ev("e0", "无时间", ts=None))
    ms, _ = _make(store, FakeQueryEngine())
    try:
        out = ms.recall(5)
        assert out.index("[id:e1]") < out.index("[id:e0]")
    finally:
        ms.shutdown()


def test_recall_same_timestamp_deterministic():
    """同 timestamp → 次序由 id 决定，不依赖存储遍历（插入）顺序。"""
    ts = "2026-06-26T00:00:00+00:00"

    def run(order: list[str]) -> str:
        store = FakeStore()
        for nid in order:
            store.add_node(_ev(nid, nid, ts=ts))
        ms, _ = _make(store, FakeQueryEngine())
        try:
            return ms.recall(5)
        finally:
            ms.shutdown()

    out1 = run(["eA", "eB", "eC"])
    out2 = run(["eC", "eB", "eA"])  # 不同插入顺序
    assert out1 == out2
    # id 倒序（reverse=True）：eC, eB, eA
    assert out1.index("[id:eC]") < out1.index("[id:eB]") < out1.index("[id:eA]")


def test_recall_token_budget_truncation():
    """渲染总 token 受 T 约束：T 仅容最近 3 条时，更早事件被截掉、总 token ≤ T。"""
    store = FakeStore()
    events = []
    for i in range(6):
        ev = _ev(f"e{i}", f"较长的记忆内容片段-{i}", ts=f"2026-06-2{i}T00:00:00+00:00")
        events.append(ev)
        store.add_node(ev)
    # 用真实渲染口径算「最近 3 条」的输出 token，作为 T（恰容 3 条、卡掉第 4 条）
    ordered = sorted(events, key=lambda n: (_event_timestamp(n), n.id), reverse=True)
    budget = TokenBudget(max_tokens=10000).estimate(_render_events(ordered[:3]))
    qe = FakeQueryEngine(token_budget_T=budget)
    ms, _ = _make(store, qe)
    try:
        out = ms.recall(100)  # limit 大，靠 T 截断
        assert qe.token_budget.estimate(out) <= qe.token_budget.T
        for nid in ("e5", "e4", "e3"):
            assert f"[id:{nid}]" in out
        assert "[id:e2]" not in out  # 第 4 条被 T 截掉
    finally:
        ms.shutdown()


def test_recall_single_event_exceeds_T():
    """单条全文就超 T → 仍无条件完整返回最近 1 条（即使越界），其余受 T 约束。"""
    store = FakeStore()
    big = "超长内容" * 200  # 单条远超极小 T
    store.add_node(_ev("e_old", "旧的短事件", ts="2026-06-20T00:00:00+00:00"))
    store.add_node(_ev("e_new", big, ts="2026-06-27T00:00:00+00:00"))
    qe = FakeQueryEngine(token_budget_T=10)  # 极小 T
    ms, _ = _make(store, qe)
    try:
        out = ms.recall(5)
        assert "[id:e_new]" in out and big in out  # 最近 1 条全文（未截正文）
        assert "[id:e_old]" not in out  # 其余严格受 T 约束
        assert qe.token_budget.estimate(out) > qe.token_budget.T  # 证明「至少 1 条」凌驾 T
    finally:
        ms.shutdown()


def test_recall_read_only():
    """recall 只读 get_all_nodes：不触发写 / 守门 / 裂变（FakeStore 仅实现读方法，
    若 recall 试图写 / 守门会 AttributeError；此处再断言节点集未变）。"""
    store = FakeStore()
    store.add_node(_ev("e1", "事件", ts="2026-06-26T00:00:00+00:00"))
    before = dict(store.nodes)
    ms, _ = _make(store, FakeQueryEngine())
    try:
        ms.recall(5)
    finally:
        ms.shutdown()
    assert store.nodes == before


def test_recall_token_budget_never_exceeds_T_when_multi():
    """铁律一：返回 ≥2 条时，渲染总 token MUST ≤ T。

    单条超 T 是 D8 允许的（最近 1 条凌驾 T），故只断言 n>=2 情形；
    采样含实现期曾失守的 T（78/108/138/168），锁死「估算 == 渲染口径」。
    """
    store = FakeStore()
    for i in range(6):
        store.add_node(
            _ev(f"e{i}", f"记忆事件内容片段编号{i}", ts=f"2026-06-2{i}T00:00:00+00:00")
        )
    for T in (50, 78, 100, 108, 138, 168, 200, 500, 2000):
        qe = FakeQueryEngine(token_budget_T=T)
        ms, _ = _make(store, qe)
        try:
            out = ms.recall(100)  # limit 大，靠 T 截断
            n = out.count("[id:")
            if n >= 2:
                assert qe.token_budget.estimate(out) <= qe.token_budget.T, (
                    f"T={T}: estimate(out)={qe.token_budget.estimate(out)} > T (n={n})"
                )
        finally:
            ms.shutdown()


# === graph_summary ===


def test_graph_summary_returns_meta():
    store = FakeStore()
    store.graph_meta["graph_summary"] = "这张图关于机器学习"
    ms, _ = _make(store, FakeQueryEngine())
    try:
        assert ms.graph_summary() == "这张图关于机器学习"
    finally:
        ms.shutdown()


def test_graph_summary_empty_when_missing():
    ms, _ = _make(FakeStore(), FakeQueryEngine())
    try:
        assert ms.graph_summary() == ""  # 无摘要返回空串
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

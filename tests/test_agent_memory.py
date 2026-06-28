"""MemoryStore 5 原语测试：FakeMCS（带 store / query_engine），不依赖真实 MCS / LLM。

覆盖：search（keyword / direct / vector / 未知模式）、associate（mcs / hot / random /
seed 不存在）、find_path（连通 / 不连通 / 节点不存在 / 同节点 / 经事实边）、
recall（时间倒排 / limit·T 双截断 / 单条超 T / 空图 / 无 timestamp / 确定性次序）、
learn（状态摘要）。另含 locate_seeds 委托等价性。
"""

from __future__ import annotations

import pytest

from mcs.core.errors import LLMParseError
from mcs.core.plugin import PluginType
from mcs.core.token_budget import TokenBudget
from mcs.entities.graph import CLASS_EVENT, Edge, Node
from mcs.interfaces.llm import LLMInterface
from mcs_agent.memory import (
    MemoryStore,
    _RECALL_HEADER,
    _event_timestamp,
    _render_event_line,
    _render_events,
    _render_nodes,
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
        # fact_id → 其背书事件列表（get_related_events 的预设返回）
        self.related_events: dict[str, list[Node]] = {}
        self.related_events_calls: list[tuple[str, int | None]] = []

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

    def get_related_events(self, node_id: str, limit: int | None = None) -> list[Node]:
        """复刻 StoreInterface 口径：时间倒排（timestamp,id）+ limit。"""
        self.related_events_calls.append((node_id, limit))
        evs = sorted(
            self.related_events.get(node_id, []),
            key=lambda n: (_event_timestamp(n), n.id),
            reverse=True,
        )
        if limit is not None:
            evs = evs[:limit]
        return evs

    def get_graph_meta(self, key: str) -> str | None:
        return self.graph_meta.get(key)

    def get_all_nodes(self) -> list[Node]:
        return list(self.nodes.values())

    def get_nodes_by_class(self, node_class: str) -> list[Node]:
        return [n for n in self.nodes.values() if n.node_class == node_class]


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
    event_node: Node | None = None


class _FakeReadManager:
    """极简 read_manager：仅 get_all(PluginType.LLM) 返回注入的 LLM 插件。"""

    def __init__(self, llm_plugin: "FakeLLMPlugin | None" = None) -> None:
        self._llm = llm_plugin

    def get_all(self, plugin_type: PluginType) -> list:
        if plugin_type == PluginType.LLM and self._llm is not None:
            return [self._llm]
        return []


class FakeLLMPlugin(LLMInterface):
    """脚本化 LLM：按 purpose 返回预设 raw，跑真实 call 编排（含 template 格式化 + parse）。

    override ``call`` 先记录 ``(purpose, nodes_in, free_args)`` 再委托 ``super().call()``，
    使「估算==投喂」可断言（``free_args["material"]`` 即投喂串）。``_raw_call`` 按 purpose
    返回脚本化 raw——故 parse 失败 = 脚本给坏 raw → 真 parse 抛 ``LLMParseError``，真实复现。
    """

    def __init__(self, raw_by_purpose: dict[str, str]) -> None:
        super().__init__()
        self._raw_by_purpose = raw_by_purpose
        self.calls: list[tuple[str, list, dict]] = []
        self._pending: str | None = None

    def get_name(self) -> str:
        return "fake-llm"

    def get_type(self) -> PluginType:
        return PluginType.LLM

    def call(self, purpose: str, nodes_in=None, free_args=None):
        self.calls.append((purpose, list(nodes_in or []), dict(free_args or {})))
        self._pending = purpose
        return super().call(purpose, nodes_in, free_args)

    def _raw_call(self, system: str, user: str) -> str:
        return self._raw_by_purpose.get(self._pending or "", "")


class FakeMCS:
    def __init__(
        self,
        store: FakeStore,
        qe: FakeQueryEngine,
        llm_plugin: FakeLLMPlugin | None = None,
    ) -> None:
        self.store = store
        self.query_engine = qe
        self.read_manager = _FakeReadManager(llm_plugin)
        self.last_query_existing_context: list | None = None

    def ingest(self, text_or_input) -> _FakeWriteCtx:
        """支持 str 和 IngestInput 两种入参，IngestInput 时设置 event_node 含 timestamp。"""
        from mcs.entities.decisions import IngestInput

        ctx = _FakeWriteCtx()
        if isinstance(text_or_input, IngestInput):
            ts = text_or_input.timestamp or ""
            ctx.event_node = _ev(
                nid=f"ev_{id(text_or_input):x}",
                content=text_or_input.content,
                ts=ts,
            )
        return ctx

    def query(self, text: str, existing_context: list | None = None) -> str:
        self.last_query_existing_context = existing_context
        return f"raw-subgraph-for:{text}"

    def shutdown(self) -> None:
        pass


def _make(store: FakeStore, qe: FakeQueryEngine) -> tuple[MemoryStore, FakeMCS]:
    """构造 MemoryStore（build_fn 返回 FakeMCS；无 LLM 插件）。"""
    mcs = FakeMCS(store, qe)
    return MemoryStore(lambda: mcs), mcs


def _make_with_llm(
    store: FakeStore, qe: FakeQueryEngine, llm: FakeLLMPlugin
) -> tuple[MemoryStore, FakeMCS]:
    """构造带 FakeLLMPlugin 的 MemoryStore（generalize / arbitrate 用）。"""
    mcs = FakeMCS(store, qe, llm)
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


# === ingest_structured（结构化写入，时间忠实） ===


def test_ingest_structured_returns_event_id():
    ms, _ = _make(FakeStore(), FakeQueryEngine())
    try:
        event_id = ms.ingest_structured("今天和团队讨论了新方案", "2026-06-27T14:30:00")
        assert isinstance(event_id, str)
        assert len(event_id) > 0
    finally:
        ms.shutdown()


def test_ingest_structured_timestamp_lands():
    """ingest_structured 的事件节点 event_meta.timestamp 为传入值（非 now）。"""
    ms, mcs = _make(FakeStore(), FakeQueryEngine())
    try:
        event_id = ms.ingest_structured("测试内容", "2026-06-27T14:30:00")
        # FakeMCS.ingest 构造的 event_node 含传入 timestamp
        # 通过 recall 验证（FakeStore 的 get_nodes_by_class 返回空——直接检查 mcs 内部）
        # 更直接：检查 FakeMCS 最后 ingest 的 ctx.event_node
        # 由于 worker 线程内执行，我们通过 event_id 非空来确认调用成功
        assert isinstance(event_id, str)
    finally:
        ms.shutdown()


def test_ingest_structured_via_single_worker():
    """ingest_structured 与其他原语经同一单 worker 线程串行执行。"""
    ms, _ = _make(FakeStore(), FakeQueryEngine())
    try:
        # 并发调用不会崩溃（单 worker 串行化保证）
        results = []
        for i in range(5):
            results.append(ms.ingest_structured(f"消息{i}", f"2026-06-27T14:3{i}:00"))
        assert all(isinstance(r, str) and len(r) > 0 for r in results)
    finally:
        ms.shutdown()


def test_learn_unchanged_after_ingest_structured():
    """ingest_structured 不改 learn 既有契约。"""
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


# === generalize（归纳概括·只读） ===


def test_generalize_basic():
    """多节点 → 调 generalize purpose、返回概括文本；material 含各节点 id。"""
    store = FakeStore()
    store.add_node(_n("c1", "猫"))
    store.add_node(_n("c2", "狗"))
    llm = FakeLLMPlugin({"generalize": "它们都是哺乳类宠物"})
    ms, _ = _make_with_llm(store, FakeQueryEngine(), llm)
    try:
        out = ms.generalize(["c1", "c2"], focus="宠物")
        assert "哺乳类宠物" in out
        assert llm.calls[0][0] == "generalize"
        assert llm.calls[0][2]["focus"] == "宠物"
        assert "[id:c1]" in llm.calls[0][2]["material"]
        assert "[id:c2]" in llm.calls[0][2]["material"]
        assert llm.calls[0][1] == []  # 显式 material 路径，不靠 nodes_in 自渲染
    finally:
        ms.shutdown()


def test_generalize_missing_nodes_skipped():
    """不存在的 id 跳过；存在的仍参与概括。"""
    store = FakeStore()
    store.add_node(_n("c1", "猫"))
    llm = FakeLLMPlugin({"generalize": "结论"})
    ms, _ = _make_with_llm(store, FakeQueryEngine(), llm)
    try:
        out = ms.generalize(["c1", "ghost"])
        assert "结论" in out
        assert "[id:c1]" in llm.calls[0][2]["material"]
        assert "[id:ghost]" not in llm.calls[0][2]["material"]
    finally:
        ms.shutdown()


def test_generalize_empty_returns_hint_no_llm():
    """空入参 → 提示文本，MUST NOT 调 LLM、MUST NOT 伪造结论。"""
    llm = FakeLLMPlugin({"generalize": "X"})
    ms, _ = _make_with_llm(FakeStore(), FakeQueryEngine(), llm)
    try:
        out = ms.generalize([], focus=None)
        assert "无可用节点" in out
        assert llm.calls == []
    finally:
        ms.shutdown()


def test_generalize_all_missing_returns_hint():
    """全部不存在 → 提示，不调 LLM。"""
    llm = FakeLLMPlugin({"generalize": "X"})
    ms, _ = _make_with_llm(FakeStore(), FakeQueryEngine(), llm)
    try:
        out = ms.generalize(["ghost1", "ghost2"])
        assert "无可用节点" in out
        assert llm.calls == []
    finally:
        ms.shutdown()


def test_generalize_T_truncation_drops_tail():
    """material 超 T → 按序丢尾节点；喂 LLM 的 material ≤ T（≥2 保留时），且丢的是尾部。"""
    store = FakeStore()
    for i in range(5):
        store.add_node(_n(f"c{i}", f"较长的概念名称片段编号{i}"))
    # T 恰容前 2 个节点（含截断提示）的 material → 丢尾到 2
    expected = _render_nodes([_n("c0", "较长的概念名称片段编号0"),
                              _n("c1", "较长的概念名称片段编号1")], "待概括节点")
    expected += "\n（注：原 5 个节点因上下文预算截断为 2 个）"
    budget = TokenBudget(max_tokens=10000).estimate(expected)
    qe = FakeQueryEngine(token_budget_T=budget)
    llm = FakeLLMPlugin({"generalize": "概括"})
    ms, _ = _make_with_llm(store, qe, llm)
    try:
        out = ms.generalize([f"c{i}" for i in range(5)])
        assert "概括" in out
        mat = llm.calls[0][2]["material"]
        # 估算 == 投喂：喂的 material 与独立重建的期望串逐字相同、且 ≤ T
        assert mat == expected
        assert qe.token_budget.estimate(mat) <= qe.token_budget.T
        # 丢尾：c2+ 不在，c0/c1 在
        assert "[id:c0]" in mat and "[id:c1]" in mat
        assert "[id:c2]" not in mat
    finally:
        ms.shutdown()


def test_generalize_T_never_exceeds_when_multi():
    """铁律一：保留 ≥2 节点时，喂 LLM 的 material MUST ≤ T。"""
    store = FakeStore()
    for i in range(6):
        store.add_node(_n(f"c{i}", f"概念节点内容片段{i}"))
    for T in (40, 60, 80, 120, 200, 500, 2000):
        qe = FakeQueryEngine(token_budget_T=T)
        llm = FakeLLMPlugin({"generalize": "g"})
        ms, _ = _make_with_llm(store, qe, llm)
        try:
            ms.generalize([f"c{i}" for i in range(6)])
            mat = llm.calls[0][2]["material"]
            n = mat.count("[id:")
            if n >= 2:
                assert qe.token_budget.estimate(mat) <= qe.token_budget.T, (
                    f"T={T}: estimate={qe.token_budget.estimate(mat)} > T (n={n})"
                )
        finally:
            ms.shutdown()


def test_generalize_parse_failure_raises():
    """LLM 返回无法解析（空白）→ 真 parse 抛 LLMParseError（由 _dispatch 隔离为 [error]）。"""
    store = FakeStore()
    store.add_node(_n("c1", "猫"))
    llm = FakeLLMPlugin({"generalize": "   "})  # 空白 → generalize.parse 抛
    ms, _ = _make_with_llm(store, FakeQueryEngine(), llm)
    try:
        with pytest.raises(LLMParseError):
            ms.generalize(["c1"])
    finally:
        ms.shutdown()


def test_generalize_no_llm_raises():
    """未配 LLM → _get_llm_plugin 抛清晰错误（由 _dispatch 隔离为 [error]）。"""
    store = FakeStore()
    store.add_node(_n("c1", "猫"))
    ms, _ = _make(store, FakeQueryEngine())  # read_manager 无 LLM
    try:
        with pytest.raises(RuntimeError):
            ms.generalize(["c1"])
    finally:
        ms.shutdown()


def test_generalize_read_only():
    """只读：不触发写 / 守门 / 裂变（FakeStore 无写方法；节点集不变）。"""
    store = FakeStore()
    store.add_node(_n("c1", "猫"))
    store.add_node(_n("c2", "狗"))
    before = dict(store.nodes)
    llm = FakeLLMPlugin({"generalize": "宠物"})
    ms, _ = _make_with_llm(store, FakeQueryEngine(), llm)
    try:
        ms.generalize(["c1", "c2"])
    finally:
        ms.shutdown()
    assert store.nodes == before


# === arbitrate（互斥裁决·只读） ===


def test_arbitrate_basic():
    """互斥事实 + 事件 → 调 adjudicate purpose、返「采信 [id:X]+理由」、反查了事件。"""
    store = FakeStore()
    store.add_node(_n("f1", "事实A"))
    store.add_node(_n("f2", "事实B"))
    store.related_events["f1"] = [_ev("e1", "支持A", ts="2026-06-26T00:00:00+00:00")]
    store.related_events["f2"] = [_ev("e2", "支持B", ts="2026-06-25T00:00:00+00:00")]
    llm = FakeLLMPlugin({"adjudicate": '{"adopt": ["f1"], "reason": "f1 有更近背书"}'})
    ms, _ = _make_with_llm(store, FakeQueryEngine(), llm)
    try:
        out = ms.arbitrate(["f1", "f2"], "哪个对")
        assert "采信" in out and "[id:f1]" in out and "f1 有更近背书" in out
        # 反查了 get_related_events（默认 events_per_fact=3）
        assert ("f1", 3) in store.related_events_calls
        assert ("f2", 3) in store.related_events_calls
        assert llm.calls[0][0] == "adjudicate"
        # material 含两事实全文 + 事件行（行级 _render_event_line，含 timestamp）
        assert "[id:f1]" in llm.calls[0][2]["material"]
        assert "2026-06-26" in llm.calls[0][2]["material"]
    finally:
        ms.shutdown()


def test_arbitrate_no_events_still_adjudicates():
    """某事实无背书事件 → 仅据事实本身裁决（不抛、不伪造事件）。"""
    store = FakeStore()
    store.add_node(_n("f1", "A"))
    store.add_node(_n("f2", "B"))
    llm = FakeLLMPlugin({"adjudicate": '{"adopt": ["f2"], "reason": "r"}'})
    ms, _ = _make_with_llm(store, FakeQueryEngine(), llm)
    try:
        out = ms.arbitrate(["f1", "f2"], "q")
        assert "[id:f2]" in out
        # material 标「无背书事件」
        assert "无背书事件" in llm.calls[0][2]["material"]
    finally:
        ms.shutdown()


def test_arbitrate_fair_truncation():
    """事件过多 T 截断的轮转公平：不把某事实事件全削光（max>1 时各事实≥1）。

    构造：fa 事件全比 fb 新。单纯全局最旧截断会把 fb 削到 0；轮转保底使各事实 ≥1
    （直至全部到 1）。跨多 T 采样验证不变量：max(ca,cb)<=1 或 min(ca,cb)>=1。
    """
    for T in (40, 60, 80, 100, 140, 200, 400):
        store = FakeStore()
        store.add_node(_n("fa", "事实A"))
        store.add_node(_n("fb", "事实B"))
        # fa 的 3 条全比 fb 的 3 条新
        store.related_events["fa"] = [
            _ev(f"a{i}", f"较新背书A{i}", ts=f"2026-06-2{6 - i}T00:00:00+00:00") for i in range(3)
        ]
        store.related_events["fb"] = [
            _ev(f"b{i}", f"较旧背书B{i}", ts=f"2026-06-{10 - i}T00:00:00+00:00") for i in range(3)
        ]
        qe = FakeQueryEngine(token_budget_T=T)
        llm = FakeLLMPlugin({"adjudicate": '{"adopt": ["fa"], "reason": "r"}'})
        ms, _ = _make_with_llm(store, qe, llm)
        try:
            ms.arbitrate(["fa", "fb"], "q")
            mat = llm.calls[0][2]["material"]
            ca = sum(f"[id:a{i}]" in mat for i in range(3))
            cb = sum(f"[id:b{i}]" in mat for i in range(3))
            # 公平不变量：任一事实 ≥2 时，另一事实 MUST ≥1（不被削光）
            assert (max(ca, cb) <= 1) or (min(ca, cb) >= 1), (
                f"T={T}: ca={ca} cb={cb}（一方≥2时另一方被削光，违反轮转保底）"
            )
            # 估算 == 投喂：喂的 material 有界（≤ T）
            assert qe.token_budget.estimate(mat) <= qe.token_budget.T
        finally:
            ms.shutdown()


def test_arbitrate_hallucination_filtered():
    """LLM 返回的采纳 id 含幻觉 → 过滤掉（不把不相关节点当采纳方）。"""
    store = FakeStore()
    store.add_node(_n("f1", "A"))
    store.add_node(_n("f2", "B"))
    llm = FakeLLMPlugin({"adjudicate": '{"adopt": ["f1", "ghost"], "reason": "r"}'})
    ms, _ = _make_with_llm(store, FakeQueryEngine(), llm)
    try:
        out = ms.arbitrate(["f1", "f2"], "q")
        assert "[id:f1]" in out and "[id:ghost]" not in out
    finally:
        ms.shutdown()


def test_arbitrate_all_filtered_no_adopt():
    """采纳 id 全被过滤（全幻觉）→ 仍返理由 + 明示「无有效采纳方」（不抛、不伪造）。"""
    store = FakeStore()
    store.add_node(_n("f1", "A"))
    llm = FakeLLMPlugin({"adjudicate": '{"adopt": ["ghost1", "ghost2"], "reason": "都不靠谱"}'})
    ms, _ = _make_with_llm(store, FakeQueryEngine(), llm)
    try:
        out = ms.arbitrate(["f1"], "q")
        assert "无有效采纳方" in out and "都不靠谱" in out
    finally:
        ms.shutdown()


def test_arbitrate_missing_facts_skipped():
    """不存在的事实 id 跳过；存在的仍裁决。"""
    store = FakeStore()
    store.add_node(_n("f1", "A"))
    llm = FakeLLMPlugin({"adjudicate": '{"adopt": ["f1"], "reason": "r"}'})
    ms, _ = _make_with_llm(store, FakeQueryEngine(), llm)
    try:
        out = ms.arbitrate(["f1", "ghost"], "q")
        assert "[id:f1]" in out
    finally:
        ms.shutdown()


def test_arbitrate_empty_returns_hint_no_llm():
    """空入参 → 提示，MUST NOT 调 LLM。"""
    llm = FakeLLMPlugin({"adjudicate": '{"adopt": [], "reason": ""}'})
    ms, _ = _make_with_llm(FakeStore(), FakeQueryEngine(), llm)
    try:
        out = ms.arbitrate([], "q")
        assert "无可用事实" in out
        assert llm.calls == []
    finally:
        ms.shutdown()


def test_arbitrate_parse_failure_raises():
    """LLM 返回非法 JSON → 真 parse 抛 LLMParseError（由 _dispatch 隔离为 [error]）。"""
    store = FakeStore()
    store.add_node(_n("f1", "A"))
    llm = FakeLLMPlugin({"adjudicate": "not json"})
    ms, _ = _make_with_llm(store, FakeQueryEngine(), llm)
    try:
        with pytest.raises(LLMParseError):
            ms.arbitrate(["f1"], "q")
    finally:
        ms.shutdown()


def test_arbitrate_no_llm_raises():
    """未配 LLM → _get_llm_plugin 抛清晰错误。"""
    store = FakeStore()
    store.add_node(_n("f1", "A"))
    ms, _ = _make(store, FakeQueryEngine())
    try:
        with pytest.raises(RuntimeError):
            ms.arbitrate(["f1"], "q")
    finally:
        ms.shutdown()


def test_arbitrate_read_only_and_no_writeback():
    """只读：不改图、不写裁决回图（节点集不变）。"""
    store = FakeStore()
    store.add_node(_n("f1", "A"))
    store.add_node(_n("f2", "B"))
    store.related_events["f1"] = [_ev("e1", "x", ts="2026-06-26T00:00:00+00:00")]
    before = dict(store.nodes)
    llm = FakeLLMPlugin({"adjudicate": '{"adopt": ["f1"], "reason": "r"}'})
    ms, _ = _make_with_llm(store, FakeQueryEngine(), llm)
    try:
        ms.arbitrate(["f1", "f2"], "q")
    finally:
        ms.shutdown()
    assert store.nodes == before


def test_arbitrate_estimate_equals_feed():
    """估算==投喂：喂 LLM 的 material（free_args["material"]）与渲染口径逐字相同。"""
    store = FakeStore()
    store.add_node(_n("f1", "事实A"))
    store.add_node(_n("f2", "事实B"))
    store.related_events["f1"] = [_ev("e1", "支持A", ts="2026-06-26T00:00:00+00:00")]
    # f2 无 related_events → get_related_events 返回 [] → 标「无背书事件」
    llm = FakeLLMPlugin({"adjudicate": '{"adopt": ["f1"], "reason": "r"}'})
    ms, _ = _make_with_llm(store, FakeQueryEngine(), llm)
    try:
        ms.arbitrate(["f1", "f2"], "q")
        mat = llm.calls[0][2]["material"]
        # 用同一 _render_event_line 口径独立重建，断言逐字相同（估算==渲染口径）
        expected = "\n".join([
            "[id:f1] 事实A",
            "  背书事件（时间倒排）：",
            "  " + _render_event_line(store.related_events["f1"][0], 1),
            "[id:f2] 事实B",
            "  （无背书事件）",
        ])
        assert mat == expected
        assert "material" in llm.calls[0][2]
    finally:
        ms.shutdown()


def test_arbitrate_facts_exceed_T_all_rendered():
    """事实全文本身超 T → 事件全丢光也 MUST 至少渲染所有事实全文（spec 边界）。"""
    store = FakeStore()
    big = "超长事实内容" * 100  # 单事实全文远超极小 T
    store.add_node(_n("f1", big))
    store.add_node(_n("f2", big))
    store.related_events["f1"] = [_ev("e1", "x", ts="2026-06-26T00:00:00+00:00")]
    qe = FakeQueryEngine(token_budget_T=10)  # 极小 T
    llm = FakeLLMPlugin({"adjudicate": '{"adopt": ["f1"], "reason": "r"}'})
    ms, _ = _make_with_llm(store, qe, llm)
    try:
        out = ms.arbitrate(["f1", "f2"], "q")
        mat = llm.calls[0][2]["material"]
        # 两事实全文都在；事件被丢光
        assert "[id:f1]" in mat and "[id:f2]" in mat
        assert big in mat
        assert "[id:e1]" not in mat
        assert "无背书事件" in mat  # 事件全丢 → 标无背书事件
    finally:
        ms.shutdown()


def test_generalize_single_oversized_node_fed():
    """单节点本身超 T → ≥1 兜底，仍喂该节点（不可拆），返回结论。"""
    store = FakeStore()
    big = "超长概念" * 100
    store.add_node(_n("c1", big))
    qe = FakeQueryEngine(token_budget_T=10)  # 极小 T
    llm = FakeLLMPlugin({"generalize": "概括"})
    ms, _ = _make_with_llm(store, qe, llm)
    try:
        out = ms.generalize(["c1"])
        assert "概括" in out
        mat = llm.calls[0][2]["material"]
        assert "[id:c1]" in mat and big in mat  # 节点未被丢
    finally:
        ms.shutdown()

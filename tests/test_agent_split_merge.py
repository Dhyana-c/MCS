"""MemoryStore.split_concept / merge_concepts 测试。

用 ``_WritableFakeStore``（完整写图 + snapshot/restore）+ mini MCS + scripted LLM
（跑真实 ``call`` 编排 → split/merge prompt parse），不依赖真实 API。覆盖：
split 两类（is_a / none）、noop、漏边降级、原子回滚、事件背书迁移、节点不存在；
merge 同义、互斥禁合、noop、aliases 收口、原子回滚、不足节点。
"""

from __future__ import annotations

import copy
import json

import pytest

from mcs.core.plugin import PluginType
from mcs.core.token_budget import TokenBudget
from mcs.entities.graph import CLASS_CONCEPT, CLASS_EVENT, CLASS_FACT, EDGE_ASSOC, EDGE_MUTEX, Edge, Node
from mcs.interfaces.llm import LLMInterface
from mcs_agent.memory import MemoryStore


# === fake 组件 ===


class _WritableFakeStore:
    """完整写图 fake：nodes dict + edges dict，支持 snapshot/restore + 载重过滤。"""

    def __init__(self) -> None:
        self.nodes: dict[str, Node] = {}
        self.edges: dict[str, Edge] = {}

    def add_node(self, n: Node) -> str:
        self.nodes[n.id] = n
        return n.id

    def get_node(self, nid: str) -> Node | None:
        return self.nodes.get(nid)

    def update_node(self, nid: str, updates: dict) -> None:
        n = self.nodes.get(nid)
        if n is None:
            return
        for k, v in updates.items():
            setattr(n, k, v)

    def delete_node(self, nid: str) -> None:
        self.nodes.pop(nid, None)
        self.edges = {
            eid: e
            for eid, e in self.edges.items()
            if e.source_id != nid and e.target_id != nid
        }

    def add_edge(self, source_id, target_id, type=EDGE_ASSOC, **kw) -> str:
        e = Edge(source_id=source_id, target_id=target_id, type=type)
        self.edges[e.id] = e
        return e.id

    def delete_edge(self, edge_id, target_id=None) -> None:
        if target_id is None:
            self.edges.pop(edge_id, None)
        else:
            self.edges = {
                eid: e
                for eid, e in self.edges.items()
                if not (e.source_id == edge_id and e.target_id == target_id)
            }

    def get_edges_between(self, s, t):
        return [e for e in self.edges.values() if e.source_id == s and e.target_id == t]

    def get_relations(self, nid, limit=None):
        es = []
        for e in self.edges.values():
            if e.source_id != nid and e.target_id != nid:
                continue
            # 载重规则：核心节点侧过滤对端为事件的关联边
            other = e.target_id if e.source_id == nid else e.source_id
            on = self.nodes.get(other)
            if on and on.node_class == CLASS_EVENT and e.type == EDGE_ASSOC:
                continue
            es.append(e)
        return es[:limit] if limit else es

    def get_related_events(self, node_id, universe=None, limit=None):
        evs = []
        for e in self.edges.values():
            if e.type != EDGE_ASSOC or e.target_id != node_id:
                continue
            src = self.nodes.get(e.source_id)
            if src and src.node_class == CLASS_EVENT:
                evs.append(src)
        if universe is not None:
            evs = [n for n in evs if n.universe == universe]
        return evs[:limit] if limit else evs

    def snapshot(self) -> dict:
        return {"nodes": copy.deepcopy(self.nodes), "edges": copy.deepcopy(self.edges)}

    def restore(self, snap: dict) -> None:
        self.nodes = copy.deepcopy(snap["nodes"])
        self.edges = copy.deepcopy(snap["edges"])


class _ScriptedLLM(LLMInterface):
    """脚本化 LLM：按 purpose 返回预设 raw，跑真实 call 编排（template + parse）。"""

    def __init__(self, raw_by_purpose: dict[str, str]) -> None:
        super().__init__()
        self._raw = raw_by_purpose
        self._pending: str | None = None
        self.calls: list = []

    def get_name(self) -> str:
        return "scripted-llm"

    def get_type(self) -> PluginType:
        return PluginType.LLM

    def call(self, purpose, nodes_in=None, free_args=None):
        self.calls.append((purpose, list(nodes_in or []), dict(free_args or {})))
        self._pending = purpose
        return super().call(purpose, nodes_in, free_args)

    def _raw_call(self, system: str, user: str) -> str:
        return self._raw.get(self._pending or "", "")


class _ReadManager:
    def __init__(self, llm):
        self._llm = llm

    def get_all(self, plugin_type):
        if plugin_type == PluginType.LLM and self._llm is not None:
            return [self._llm]
        return []


class _MiniMCS:
    def __init__(self, store, llm):
        self.store = store
        self.query_engine = type("QE", (), {"token_budget": TokenBudget(max_tokens=8000)})()
        self.read_manager = _ReadManager(llm)
        self.compaction_calls: list[list] = []

    def run_compaction(self, changed_nodes) -> None:
        self.compaction_calls.append(list(changed_nodes))


def _make(store, llm):
    mcs = _MiniMCS(store, llm)
    return MemoryStore(lambda: mcs), mcs


def _concept(nid, name, content=None):
    return Node(id=nid, name=name, content=content if content is not None else name, node_class=CLASS_CONCEPT)


def _event(nid, content):
    return Node(id=nid, name=content, content=content, node_class=CLASS_EVENT)


def _fact(nid, content):
    return Node(id=nid, name=content, content=content, node_class=CLASS_FACT)


# === split 测试 ===


def test_split_is_a_parent_child_linked():
    """4.1 类别-特化：拆成 parent + child，is_a → child→parent 关联边，原边按归属迁。"""
    store = _WritableFakeStore()
    store.add_node(_concept("n1", "按摩", "按摩是手法疗法；泰式以拉伸为主"))
    store.add_node(_concept("tool", "手法"))
    store.add_node(_concept("thai_feat", "拉伸为主"))
    store.add_edge("n1", "tool", type=EDGE_ASSOC)  # 大类级边 → 归 parent
    store.add_edge("n1", "thai_feat", type=EDGE_ASSOC)  # 特化级边 → 归 child
    raw = json.dumps(
        {
            "action": "split",
            "into": [
                {"name": "按摩", "content": "手法疗法（大类）", "role": "parent"},
                {"name": "泰式按摩", "content": "以拉伸为主", "role": "child"},
            ],
            "relation": "is_a",
            "edges": [
                {"counterpart": "手法", "to": "按摩"},
                {"counterpart": "拉伸为主", "to": "泰式按摩"},
            ],
        }
    )
    ms, mcs = _make(store, _ScriptedLLM({"split": raw}))
    res = ms.split_concept("n1")
    assert "已拆分" in res
    assert "n1" not in store.nodes  # 原节点删
    names = {n.name: n.id for n in store.nodes.values()}
    assert "按摩" in names and "泰式按摩" in names
    pid, cid = names["按摩"], names["泰式按摩"]
    # is_a → child→parent 关联边
    assert store.get_edges_between(cid, pid), "child→parent 关联边缺失"
    # 原边迁对端：手法 → 按摩(parent)；拉伸为主 → 泰式按摩(child)
    assert store.get_edges_between(pid, "tool")
    assert store.get_edges_between(cid, "thai_feat")
    assert mcs.compaction_calls  # 过守门


def test_split_none_siblings_no_is_a():
    """4.1 多实体误并：拆成平级 sibling，relation=none，无 is_a 边。"""
    store = _WritableFakeStore()
    store.add_node(_concept("n1", "小明和小红", "小明 28 岁；小红做设计"))
    store.add_node(_concept("xm_age", "28 岁"))
    store.add_node(_concept("xh_job", "设计"))
    store.add_edge("n1", "xm_age", type=EDGE_ASSOC)
    store.add_edge("n1", "xh_job", type=EDGE_ASSOC)
    raw = json.dumps(
        {
            "action": "split",
            "into": [
                {"name": "小明", "content": "小明，28 岁", "role": "sibling"},
                {"name": "小红", "content": "小红，做设计", "role": "sibling"},
            ],
            "relation": "none",
            "edges": [
                {"counterpart": "28 岁", "to": "小明"},
                {"counterpart": "设计", "to": "小红"},
            ],
        }
    )
    ms, _ = _make(store, _ScriptedLLM({"split": raw}))
    res = ms.split_concept("n1")
    assert "已拆分" in res
    names = {n.name: n.id for n in store.nodes.values()}
    xm, xh = names["小明"], names["小红"]
    # none 型：sibling 间无 is_a 边
    assert not store.get_edges_between(xm, xh) and not store.get_edges_between(xh, xm)
    assert store.get_edges_between(xm, "xm_age")
    assert store.get_edges_between(xh, "xh_job")


def test_split_noop_no_change():
    """4.2 noop：专用 prompt 复核未耦合 → 不改图、不调守门。"""
    store = _WritableFakeStore()
    store.add_node(_concept("n1", "狗", "一种常见家畜"))
    snap_before = store.snapshot()
    ms, mcs = _make(store, _ScriptedLLM({"split": '{"action": "noop"}'}))
    res = ms.split_concept("n1")
    assert "未拆分" in res
    assert store.snapshot() == snap_before  # 图未动
    assert not mcs.compaction_calls


def test_split_missing_edge_fallback_to_parent():
    """4.3 漏边降级：edge_plan 漏指的原边透明挂 parent，返回含提示。"""
    store = _WritableFakeStore()
    store.add_node(_concept("n1", "按摩", "按摩...泰式..."))
    store.add_node(_concept("a", "A"))
    store.add_node(_concept("b", "B"))
    store.add_node(_concept("c", "C"))
    store.add_edge("n1", "a", type=EDGE_ASSOC)
    store.add_edge("n1", "b", type=EDGE_ASSOC)
    store.add_edge("n1", "c", type=EDGE_ASSOC)  # 这条会被漏指
    raw = json.dumps(
        {
            "action": "split",
            "into": [
                {"name": "按摩", "content": "大类", "role": "parent"},
                {"name": "泰式按摩", "content": "特化", "role": "child"},
            ],
            "relation": "is_a",
            "edges": [
                {"counterpart": "A", "to": "按摩"},
                {"counterpart": "B", "to": "泰式按摩"},
                # C 漏指
            ],
        }
    )
    ms, _ = _make(store, _ScriptedLLM({"split": raw}))
    res = ms.split_concept("n1")
    assert "暂挂" in res and "C" in res
    names = {n.name: n.id for n in store.nodes.values()}
    # 漏的 c 边挂到 parent（按摩）
    assert store.get_edges_between(names["按摩"], "c")


def test_split_event_endorsement_migrated_to_parent():
    """4.6 事件背书边自动迁 target 到 parent（不丢、不交 LLM）。"""
    store = _WritableFakeStore()
    store.add_node(_concept("n1", "按摩", "按摩...泰式..."))
    store.add_node(_event("ev1", "今天体验了按摩"))
    store.add_edge("ev1", "n1", type=EDGE_ASSOC)  # 事件背书
    store.add_node(_concept("a", "A"))
    store.add_edge("n1", "a", type=EDGE_ASSOC)
    raw = json.dumps(
        {
            "action": "split",
            "into": [
                {"name": "按摩", "content": "大类", "role": "parent"},
                {"name": "泰式按摩", "content": "特化", "role": "child"},
            ],
            "relation": "is_a",
            "edges": [{"counterpart": "A", "to": "按摩"}],
        }
    )
    ms, _ = _make(store, _ScriptedLLM({"split": raw}))
    ms.split_concept("n1")
    names = {n.name: n.id for n in store.nodes.values()}
    # 事件背书边 target 迁到 parent
    assert store.get_edges_between("ev1", names["按摩"])
    assert not store.get_edges_between("ev1", "n1")  # 原节点已删


def test_split_atomic_rollback_on_failure():
    """4.5 原子回滚：执行中注入失败 → restore → 图回原状（无半拆分）。"""
    store = _WritableFakeStore()
    store.add_node(_concept("n1", "按摩", "按摩...泰式..."))
    store.add_node(_concept("a", "A"))
    store.add_edge("n1", "a", type=EDGE_ASSOC)
    snap_before = store.snapshot()
    raw = json.dumps(
        {
            "action": "split",
            "into": [
                {"name": "按摩", "content": "大类", "role": "parent"},
                {"name": "泰式按摩", "content": "特化", "role": "child"},
            ],
            "relation": "is_a",
            "edges": [{"counterpart": "A", "to": "按摩"}],
        }
    )

    # 注入失败：delete_node 抛（执行末段）
    original_delete = store.delete_node

    def boom(nid):
        if nid == "n1":
            raise RuntimeError("注入失败")
        return original_delete(nid)

    store.delete_node = boom
    ms, mcs = _make(store, _ScriptedLLM({"split": raw}))
    with pytest.raises(RuntimeError):
        ms.split_concept("n1")
    # 回滚：图回到原状
    assert store.snapshot() == snap_before
    assert not mcs.compaction_calls  # 失败前未到守门


def test_split_node_not_exists():
    """4.12 节点不存在：返回提示、不抛、不调 LLM。"""
    store = _WritableFakeStore()
    llm = _ScriptedLLM({"split": '{"action": "noop"}'})
    ms, _ = _make(store, llm)
    res = ms.split_concept("ghost")
    assert "不存在" in res
    assert llm.calls == []  # 没调 LLM


def test_split_parse_failure_isolated():
    """split purpose LLM 返回坏 JSON → LLMParseError → _dispatch 隔离（parse 在 call 内）。"""
    store = _WritableFakeStore()
    store.add_node(_concept("n1", "按摩", "..."))
    ms, _ = _make(store, _ScriptedLLM({"split": "not json"}))
    # _do_split 内 llm.call 会抛 LLMParseError（parse 失败）；经 _submit 抛出
    from mcs.core.errors import LLMParseError

    with pytest.raises(LLMParseError):
        ms.split_concept("n1")


# === merge 测试 ===


def test_merge_synonym_edges_migrated():
    """4.7 同义合并：absorb 的边迁 keep、absorb 删除。"""
    store = _WritableFakeStore()
    store.add_node(_concept("a", "苹果公司", "科技公司"))
    store.add_node(_concept("b", "Apple Inc.", "tech company"))
    store.add_node(_concept("c", "库克"))
    store.add_edge("a", "c", type=EDGE_ASSOC)
    store.add_edge("b", "c", type=EDGE_ASSOC)  # b 的边，应迁到 a
    raw = json.dumps(
        {
            "action": "merge",
            "keep": "a",
            "absorb": ["b"],
            "merged_content": "苹果公司（Apple Inc.），科技巨头",
            "aliases_to_add": ["Apple"],
        }
    )
    ms, mcs = _make(store, _ScriptedLLM({"merge": raw}))
    res = ms.merge_concepts(["a", "b"])
    assert "已合并" in res
    assert "a" in store.nodes and "b" not in store.nodes
    # b→c 边迁到 a→c（add_edge 去重，a→c 已存在则一条）
    assert store.get_edges_between("a", "c")
    assert mcs.compaction_calls


def test_merge_mutex_rejected_mechanism_guard():
    """4.8 互斥禁合：LLM 漏判返回 merge，机制层扫互斥边拒绝、不改图。"""
    store = _WritableFakeStore()
    store.add_node(_fact("fa", "说法A"))
    store.add_node(_fact("fb", "说法B"))
    store.add_edge("fa", "fb", type=EDGE_MUTEX)  # 互斥
    snap_before = store.snapshot()
    raw = json.dumps(
        {"action": "merge", "keep": "fa", "absorb": ["fb"], "merged_content": "合并"}
    )
    ms, _ = _make(store, _ScriptedLLM({"merge": raw}))
    res = ms.merge_concepts(["fa", "fb"])
    assert "互斥禁合" in res
    assert store.snapshot() == snap_before  # 未改图


def test_merge_noop_no_change():
    """4.9 noop：非同义 → 不改图。"""
    store = _WritableFakeStore()
    store.add_node(_concept("a", "苹果", "水果"))
    store.add_node(_concept("b", "苹果", "公司"))
    snap_before = store.snapshot()
    ms, mcs = _make(store, _ScriptedLLM({"merge": '{"action": "noop", "reason": "同名异义"}'}))
    res = ms.merge_concepts(["a", "b"])
    assert "未合并" in res
    assert store.snapshot() == snap_before
    assert not mcs.compaction_calls


def test_merge_aliases_consolidated():
    """4.10 aliases 收口：absorb 的 name + aliases_to_add 并入 keep.aliases。"""
    store = _WritableFakeStore()
    store.add_node(_concept("a", "苹果公司", "tech"))
    store.add_node(_concept("b", "Apple Inc.", "tech"))
    raw = json.dumps(
        {
            "action": "merge",
            "keep": "a",
            "absorb": ["b"],
            "merged_content": "",
            "aliases_to_add": ["Apple", "AAPL"],
        }
    )
    ms, _ = _make(store, _ScriptedLLM({"merge": raw}))
    ms.merge_concepts(["a", "b"])
    keep = store.get_node("a")
    # 别名落 alias_index.aliases（与 core write_pipeline / AliasIndexPlugin 对齐）
    aliases = keep.extensions.get("alias_index", {}).get("aliases", [])
    assert "Apple" in aliases and "AAPL" in aliases
    assert "Apple Inc." in aliases  # absorb 的 name 也并入


def test_merge_atomic_rollback_on_failure():
    """4.10 原子回滚：执行中失败 → restore。"""
    store = _WritableFakeStore()
    store.add_node(_concept("a", "A"))
    store.add_node(_concept("b", "B"))
    store.add_node(_concept("c", "C"))
    store.add_edge("b", "c", type=EDGE_ASSOC)
    snap_before = store.snapshot()
    raw = json.dumps({"action": "merge", "keep": "a", "absorb": ["b"]})

    original_delete = store.delete_node
    store.delete_node = lambda nid: (_ for _ in ()).throw(RuntimeError("boom")) if nid == "b" else original_delete(nid)
    ms, _ = _make(store, _ScriptedLLM({"merge": raw}))
    with pytest.raises(RuntimeError):
        ms.merge_concepts(["a", "b"])
    assert store.snapshot() == snap_before


def test_merge_insufficient_nodes():
    """4.12 不足 2 个有效节点 → 提示、不调 LLM。"""
    store = _WritableFakeStore()
    store.add_node(_concept("a", "A"))
    llm = _ScriptedLLM({"merge": '{"action": "noop"}'})
    ms, _ = _make(store, llm)
    res = ms.merge_concepts(["a"])  # 仅 1 个
    assert "不足" in res
    assert llm.calls == []


def test_merge_hallucination_id_rejected():
    """keep/absorb 含不在传入集合的 id → 拒绝（幻觉 id）。"""
    store = _WritableFakeStore()
    store.add_node(_concept("a", "A"))
    store.add_node(_concept("b", "B"))
    snap_before = store.snapshot()
    raw = json.dumps({"action": "merge", "keep": "a", "absorb": ["ghost"]})
    ms, _ = _make(store, _ScriptedLLM({"merge": raw}))
    res = ms.merge_concepts(["a", "b"])
    assert "幻觉" in res or "error" in res
    assert store.snapshot() == snap_before


# === core public 守门入口（Task 0.3）===


def test_mcs_run_compaction_forwards():
    """0.3 MCS.run_compaction 转发 write_pipeline.run_compaction。"""
    from mcs.core.mcs import MCS

    recorded: list = []

    class _WP:
        def run_compaction(self, changed_nodes):
            recorded.append(list(changed_nodes))

    mcs = MCS(
        write_pipeline=_WP(),
        query_engine=None,
        store=None,
        write_manager=None,
        read_manager=None,
    )
    mcs.run_compaction([1, 2, 3])
    assert recorded == [[1, 2, 3]]


def test_write_pipeline_run_compaction_forwards_internal():
    """0.3 WritePipeline.run_compaction 转发 _run_compaction（不改既有逻辑、ingest 仍调私有）。"""
    from mcs.core.write_pipeline import WritePipeline

    recorded: list = []
    wp = WritePipeline.__new__(WritePipeline)  # 不跑 __init__（避免重依赖）
    wp._run_compaction = lambda changed: recorded.append(list(changed))  # type: ignore[attr-defined]
    wp.run_compaction(["a", "b"])
    assert recorded == [["a", "b"]]


# === split 跨关系边物化 fact（Task 4.4）===


def test_split_cross_relation_edge_becomes_fact():
    """4.4 跨两产物关系的原边 → 物化为 role=fact 节点承接（CLASS_FACT + 边迁到它）。"""
    store = _WritableFakeStore()
    store.add_node(_concept("n1", "小明和小红", "两人是夫妻；小明 28；小红做设计"))
    store.add_node(_concept("marriage", "婚姻"))
    store.add_edge("n1", "marriage", type=EDGE_ASSOC)
    raw = json.dumps(
        {
            "action": "split",
            "into": [
                {"name": "小明", "content": "28 岁", "role": "sibling"},
                {"name": "小红", "content": "做设计", "role": "sibling"},
                {"name": "小明和小红的婚姻", "content": "两人是夫妻", "role": "fact"},
            ],
            "relation": "none",
            "edges": [{"counterpart": "婚姻", "to": "小明和小红的婚姻"}],
        }
    )
    ms, _ = _make(store, _ScriptedLLM({"split": raw}))
    ms.split_concept("n1")
    by_name = {n.name: n for n in store.nodes.values()}
    assert "小明和小红的婚姻" in by_name
    fact = by_name["小明和小红的婚姻"]
    assert fact.node_class == CLASS_FACT  # 物化为事实节点
    # 原边（到"婚姻"）迁到 fact 产物
    assert store.get_edges_between(fact.id, "marriage")
    # fact 产物连两端概念（sibling），使 fact 在图中可达
    xm_id = by_name["小明"].id
    xh_id = by_name["小红"].id
    assert store.get_edges_between(fact.id, xm_id) or store.get_edges_between(xm_id, fact.id)
    assert store.get_edges_between(fact.id, xh_id) or store.get_edges_between(xh_id, fact.id)


# === absorb↔absorb 互斥禁合 ===


def test_merge_absorb_absorb_mutex_rejected():
    """absorb 间互斥：合并后等价于 keep 自身互斥矛盾 → 机制层拒绝。"""
    store = _WritableFakeStore()
    store.add_node(_fact("fa", "说法A"))
    store.add_node(_fact("fb", "说法B"))
    store.add_node(_concept("fc", "C"))
    store.add_edge("fa", "fb", type=EDGE_MUTEX)  # absorb 间互斥
    snap_before = store.snapshot()
    raw = json.dumps({"action": "merge", "keep": "fc", "absorb": ["fa", "fb"], "merged_content": "合并"})
    ms, _ = _make(store, _ScriptedLLM({"merge": raw}))
    res = ms.merge_concepts(["fa", "fb", "fc"])
    assert "互斥禁合" in res
    assert store.snapshot() == snap_before  # 未改图


# === 守门异常回滚 ===


def test_split_compaction_failure_rollback():
    """split 守门抛异常 → restore → 图回原状。"""
    store = _WritableFakeStore()
    store.add_node(_concept("n1", "按摩", "按摩...泰式..."))
    store.add_node(_concept("a", "A"))
    store.add_edge("n1", "a", type=EDGE_ASSOC)
    snap_before = store.snapshot()
    raw = json.dumps(
        {
            "action": "split",
            "into": [
                {"name": "按摩", "content": "大类", "role": "parent"},
                {"name": "泰式按摩", "content": "特化", "role": "child"},
            ],
            "relation": "is_a",
            "edges": [{"counterpart": "A", "to": "按摩"}],
        }
    )

    class _BoomMCS(_MiniMCS):
        def run_compaction(self, changed_nodes):
            raise RuntimeError("守门失败")

    mcs = _BoomMCS(store, _ScriptedLLM({"split": raw}))
    ms = MemoryStore(lambda: mcs)
    with pytest.raises(RuntimeError, match="守门失败"):
        ms.split_concept("n1")
    assert store.snapshot() == snap_before  # 回滚


def test_merge_compaction_failure_rollback():
    """merge 守门抛异常 → restore → 图回原状。"""
    store = _WritableFakeStore()
    store.add_node(_concept("a", "A"))
    store.add_node(_concept("b", "B"))
    store.add_node(_concept("c", "C"))
    store.add_edge("b", "c", type=EDGE_ASSOC)
    snap_before = store.snapshot()
    raw = json.dumps({"action": "merge", "keep": "a", "absorb": ["b"]})

    class _BoomMCS(_MiniMCS):
        def run_compaction(self, changed_nodes):
            raise RuntimeError("守门失败")

    mcs = _BoomMCS(store, _ScriptedLLM({"merge": raw}))
    ms = MemoryStore(lambda: mcs)
    with pytest.raises(RuntimeError, match="守门失败"):
        ms.merge_concepts(["a", "b"])
    assert store.snapshot() == snap_before  # 回滚


# === split is_a 型 fact 产物连 parent + child ===


def test_split_is_a_fact_linked_to_parent_and_child():
    """is_a 型拆分中 fact 产物连 parent 和 child，使 fact 可达。"""
    store = _WritableFakeStore()
    store.add_node(_concept("n1", "按摩", "按摩是手法疗法；泰式以拉伸为主；两者有传承关系"))
    store.add_node(_concept("a", "A"))
    store.add_edge("n1", "a", type=EDGE_ASSOC)
    raw = json.dumps(
        {
            "action": "split",
            "into": [
                {"name": "按摩", "content": "手法疗法（大类）", "role": "parent"},
                {"name": "泰式按摩", "content": "以拉伸为主", "role": "child"},
                {"name": "泰式按摩的传承", "content": "两者有传承关系", "role": "fact"},
            ],
            "relation": "is_a",
            "edges": [{"counterpart": "A", "to": "按摩"}],
        }
    )
    ms, _ = _make(store, _ScriptedLLM({"split": raw}))
    ms.split_concept("n1")
    by_name = {n.name: n for n in store.nodes.values()}
    fact = by_name["泰式按摩的传承"]
    pid = by_name["按摩"].id
    cid = by_name["泰式按摩"].id
    # fact 连 parent
    assert store.get_edges_between(fact.id, pid) or store.get_edges_between(pid, fact.id)
    # fact 连 child
    assert store.get_edges_between(fact.id, cid) or store.get_edges_between(cid, fact.id)


# === B 组补充：node_class 校验 / hub 迁移 / 互斥第三闸 / fact 全连 ===


def test_split_rejects_non_concept_node():
    """B2 split 仅拆概念节点：传 fact id → 拒绝、不调 LLM、不改图。"""
    store = _WritableFakeStore()
    store.add_node(_fact("f1", "事实"))
    snap_before = store.snapshot()
    llm = _ScriptedLLM({"split": '{"action": "noop"}'})
    ms, _ = _make(store, llm)
    res = ms.split_concept("f1")
    assert "仅拆概念节点" in res
    assert llm.calls == []  # 没调 LLM
    assert store.snapshot() == snap_before


def test_merge_rejects_mutex_when_keep_not_fact():
    """B2 互斥第三闸：absorb 带互斥边、keep 非 fact → 拒绝（无法承接）、不改图。"""
    store = _WritableFakeStore()
    store.add_node(_concept("keep", "概念K"))
    store.add_node(_fact("fa", "说法A"))
    store.add_node(_fact("fx", "外部事实"))
    store.add_edge("fa", "fx", type=EDGE_MUTEX)  # absorb fa 带互斥边（↔外部 fact）
    snap_before = store.snapshot()
    raw = json.dumps({"action": "merge", "keep": "keep", "absorb": ["fa"], "merged_content": "合并"})
    ms, _ = _make(store, _ScriptedLLM({"merge": raw}))
    res = ms.merge_concepts(["keep", "fa"])
    assert "互斥禁合" in res and "非 fact" in res
    assert store.snapshot() == snap_before


def test_merge_inherits_absorb_hub():
    """B1 merge：absorb 为组织中心（hub=True）→ keep 继承 hub 标记。"""
    store = _WritableFakeStore()
    store.add_node(_concept("keep", "概念K"))
    absorb = _concept("abs", "概念A")
    absorb.hub = True
    store.add_node(absorb)
    raw = json.dumps({"action": "merge", "keep": "keep", "absorb": ["abs"]})
    ms, _ = _make(store, _ScriptedLLM({"merge": raw}))
    ms.merge_concepts(["keep", "abs"])
    assert store.get_node("keep").hub is True


def test_split_parent_inherits_hub():
    """B1 split：原节点 hub=True → parent 产物继承、child 产物不继承。"""
    store = _WritableFakeStore()
    node = _concept("n1", "按摩", "按摩...泰式...")
    node.hub = True
    store.add_node(node)
    store.add_node(_concept("a", "A"))
    store.add_edge("n1", "a", type=EDGE_ASSOC)
    raw = json.dumps(
        {
            "action": "split",
            "into": [
                {"name": "按摩", "content": "大类", "role": "parent"},
                {"name": "泰式按摩", "content": "特化", "role": "child"},
            ],
            "relation": "is_a",
            "edges": [{"counterpart": "A", "to": "按摩"}],
        }
    )
    ms, _ = _make(store, _ScriptedLLM({"split": raw}))
    ms.split_concept("n1")
    by_name = {n.name: n for n in store.nodes.values()}
    assert by_name["按摩"].hub is True  # parent 继承
    assert by_name["泰式按摩"].hub is False  # child 不继承


def test_split_fact_links_all_children():
    """B3 is_a + 多 child + fact：fact 连所有 child（不只首个）。"""
    store = _WritableFakeStore()
    store.add_node(_concept("n1", "按摩", "按摩...泰式...日式...传承"))
    raw = json.dumps(
        {
            "action": "split",
            "into": [
                {"name": "按摩", "content": "大类", "role": "parent"},
                {"name": "泰式按摩", "content": "拉伸", "role": "child"},
                {"name": "日式按摩", "content": "指压", "role": "child"},
                {"name": "传承关系", "content": "有传承", "role": "fact"},
            ],
            "relation": "is_a",
            "edges": [],  # n1 孤立无原边；fact 仍连 parent + 两 child
        }
    )
    ms, _ = _make(store, _ScriptedLLM({"split": raw}))
    ms.split_concept("n1")
    by_name = {n.name: n for n in store.nodes.values()}
    fact = by_name["传承关系"]
    thai = by_name["泰式按摩"]
    nikki = by_name["日式按摩"]
    parent = by_name["按摩"]
    assert store.get_edges_between(fact.id, parent.id) or store.get_edges_between(parent.id, fact.id)
    assert store.get_edges_between(fact.id, thai.id) or store.get_edges_between(thai.id, fact.id)
    assert store.get_edges_between(fact.id, nikki.id) or store.get_edges_between(nikki.id, fact.id)

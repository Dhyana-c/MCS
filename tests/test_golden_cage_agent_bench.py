# -*- coding: utf-8 -*-
"""bench.golden_cage 的 agent 建图/查询评测组件测试（不调真实 LLM）。"""

import json
import sqlite3
from pathlib import Path

from mcs.entities.decisions import IngestInput
from mcs.entities.graph import EDGE_ASSOC, EDGE_MUTEX, Edge, Node

from bench.golden_cage.builder import BUILD_TOOLS, BuildMemory, built_titles
from bench.golden_cage.runner import (
    NULL_ANSWER,
    QUERY_TOOLS,
    CapturingMemory,
    write_report,
)
from mcs_agent.tools import BUILTIN_TOOLS


# ---------- fakes ----------


class _FakeStore:
    def __init__(self):
        self.save_full_calls = 0

    def save_full(self):
        self.save_full_calls += 1


class _FakeWriteCtx:
    changed = [1, 2]
    concepts = [1]
    persisted = True


class _FakeMCS:
    """捕获 ingest 入参的极简 MCS（BuildMemory 只碰 ingest 与 store.save_full）。"""

    def __init__(self):
        self.store = _FakeStore()
        self.ingest_calls: list[tuple] = []

    def ingest(self, data, **metadata):
        self.ingest_calls.append((data, metadata))
        return _FakeWriteCtx()

    def shutdown(self):
        pass


class _FakeNode:
    def __init__(self, nid):
        self.id = nid


# ---------- BuildMemory ----------


def test_build_memory_pins_scene_text_and_metadata():
    """learn 写入钉死的场景原文（忽略 LLM 转述）并注入 doc 级溯源。"""
    mcs = _FakeMCS()
    mem = BuildMemory(lambda: mcs)
    try:
        mem.set_scene("第一章·场景01", "场景原文完整内容。", "2039-07-01 08:00:00")
        out = mem.learn("LLM 自己转述的内容（不应入图）")
        assert "已写入" in out
        assert len(mcs.ingest_calls) == 1
        data, metadata = mcs.ingest_calls[0]
        assert isinstance(data, IngestInput)
        assert data.content == "场景原文完整内容。"  # 保真：写的是原文不是转述
        assert data.timestamp == "2039-07-01 08:00:00"
        assert metadata["doc_id"] == "第一章·场景01"
        assert metadata["chunk_id"] == "0"
    finally:
        mem.shutdown()


def test_build_memory_idempotent_within_scene():
    """同场景第二次 learn 不重复 ingest；换场景后恢复可写。"""
    mcs = _FakeMCS()
    mem = BuildMemory(lambda: mcs)
    try:
        mem.set_scene("第一章·场景01", "内容A", "t1")
        mem.learn("")
        again = mem.learn("")
        assert len(mcs.ingest_calls) == 1
        assert "已写入" in again and "无需重复" in again
        assert mem.learn_calls == 2

        mem.set_scene("第一章·场景02", "内容B", "t2")
        assert mem.scene_written is False and mem.learn_calls == 0
        mem.learn("")
        assert len(mcs.ingest_calls) == 2
        assert mcs.ingest_calls[1][1]["doc_id"] == "第一章·场景02"
    finally:
        mem.shutdown()


def test_build_memory_save_full_delegates():
    mcs = _FakeMCS()
    mem = BuildMemory(lambda: mcs)
    try:
        mem.save_full()
        assert mcs.store.save_full_calls == 1
    finally:
        mem.shutdown()


# ---------- built_titles（断点续跑口径） ----------


def test_built_titles_missing_and_empty_db(tmp_path):
    assert built_titles(tmp_path / "nope.db") == set()
    empty = tmp_path / "empty.db"
    sqlite3.connect(str(empty)).close()  # 有文件、无 document_chunks 表
    assert built_titles(empty) == set()


def test_built_titles_reads_doc_ids(tmp_path):
    db = tmp_path / "g.db"
    conn = sqlite3.connect(str(db))
    conn.execute("CREATE TABLE document_chunks (doc_id TEXT, chunk_id TEXT)")
    conn.executemany(
        "INSERT INTO document_chunks VALUES (?, ?)",
        [("第一章·场景01", "0"), ("第一章·场景01", "0"), ("第二章·场景03", "0")],
    )
    conn.commit()
    conn.close()
    assert built_titles(db) == {"第一章·场景01", "第二章·场景03"}


# ---------- CapturingMemory ----------


def test_touched_nodes_dedup_keeps_order():
    mem = CapturingMemory(lambda: _FakeMCS())
    try:
        a, b, c = _FakeNode("a"), _FakeNode("b"), _FakeNode("c")
        mem.records = [
            {"tool": "search", "args": {}, "nodes": [a, b]},
            {"tool": "associate", "args": {}, "nodes": [b, c, a]},
        ]
        assert [n.id for n in mem.touched_nodes()] == ["a", "b", "c"]
    finally:
        mem.shutdown()


# ---------- D1：CapturingMemory._do_associate 捕获一跳邻居 ----------


class _NeighborStore:
    """mini store：get_node + get_relations（_do_associate / _capture_neighbor_nodes 所需）。"""

    def __init__(self, nodes: dict, edges: list):
        self.nodes = nodes
        self.edges = edges

    def get_node(self, nid: str):
        return self.nodes.get(nid)

    def get_nodes(self, nids: list):
        return [self.nodes[n] for n in nids if n in self.nodes]

    def get_relations(self, nid: str):
        return [e for e in self.edges if e.source_id == nid or e.target_id == nid]


class _NeighborMCS:
    def __init__(self, store):
        self.store = store

    def shutdown(self):
        pass


def _neighbor_fixture():
    """seed s1 + 2 互斥邻居 + 3 关联邻居。"""
    nodes = {f"id_{c}": Node(id=f"id_{c}", name=c, content=c)
             for c in ["s1", "m1", "m2", "a1", "a2", "a3"]}
    edges = [
        Edge(source_id="id_m1", target_id="id_s1", type=EDGE_MUTEX),
        Edge(source_id="id_m2", target_id="id_s1", type=EDGE_MUTEX),
        Edge(source_id="id_s1", target_id="id_a1", type=EDGE_ASSOC),
        Edge(source_id="id_s1", target_id="id_a2", type=EDGE_ASSOC),
        Edge(source_id="id_s1", target_id="id_a3", type=EDGE_ASSOC),
    ]
    return _NeighborStore(nodes, edges)


def test_associate_captures_all_neighbors():
    """D1：_do_associate 把一跳邻居（互斥+关联）入 records['nodes']。"""
    mem = CapturingMemory(lambda: _NeighborMCS(_neighbor_fixture()))
    try:
        mem._do_associate("id_s1", 60)  # cap=60 全收
        rec = mem.records[-1]
        assert rec["tool"] == "associate"
        assert {n.id for n in rec["nodes"]} == {
            "id_m1", "id_m2", "id_a1", "id_a2", "id_a3",
        }
    finally:
        mem.shutdown()


def test_associate_limit_truncates_assoc_after_mutex():
    """D1：cap 截断——limit=2 时互斥占满 cap、关联邻居不进 records（与基类同口径）。"""
    mem = CapturingMemory(lambda: _NeighborMCS(_neighbor_fixture()))
    try:
        mem._do_associate("id_s1", 2)
        rec = mem.records[-1]
        assert {n.id for n in rec["nodes"]} == {"id_m1", "id_m2"}
    finally:
        mem.shutdown()


def test_associate_missing_seed_empty_nodes():
    """D1：seed 不存在 → records['nodes'] 空（不抛）。"""
    mem = CapturingMemory(lambda: _NeighborMCS(_NeighborStore({}, [])))
    try:
        mem._do_associate("ghost", 60)
        assert mem.records[-1]["nodes"] == []
    finally:
        mem.shutdown()


# ---------- 工具集配置有效性 ----------


def test_toolsets_are_valid_builtin_names():
    assert set(BUILD_TOOLS) <= set(BUILTIN_TOOLS)
    assert set(QUERY_TOOLS) <= set(BUILTIN_TOOLS)
    # 查询工具集必须全只读（查询 MUST NOT 写图）
    assert all(BUILTIN_TOOLS[n].readonly for n in QUERY_TOOLS)
    # 建图工具集必须含唯一写入口 learn
    assert "learn" in BUILD_TOOLS


# ---------- write_report（指标 + null 封闭语料口径） ----------


def test_write_report_metrics_and_null_accuracy(tmp_path):
    results = [
        # 非 null：一命中一未命中
        {"query_id": "q1", "type": "inference_query", "gold": ["第一章·场景01"],
         "ranked": ["第一章·场景01", "第二章·场景02"], "reached_gold": ["第一章·场景01"],
         "n_tools": 3, "n_nodes": 5, "n_llm_agent": 4, "tokens_agent": 1000,
         "wall_s": 10.0, "reply": "答案A"},
        {"query_id": "q2", "type": "comparison_query", "gold": ["第三章·场景03"],
         "ranked": ["第四章·场景04"], "reached_gold": [],
         "n_tools": 2, "n_nodes": 3, "n_llm_agent": 3, "tokens_agent": 800,
         "wall_s": 8.0, "reply": "答案B"},
        # null：一个按口径答对、一个臆答
        {"query_id": "q3", "type": "null_query", "gold": [], "ranked": [],
         "reached_gold": [], "n_tools": 2, "n_nodes": 0, "n_llm_agent": 3,
         "tokens_agent": 500, "wall_s": 5.0, "reply": NULL_ANSWER},
        {"query_id": "q4", "type": "null_query", "gold": [], "ranked": ["第一章·场景01"],
         "reached_gold": [], "n_tools": 2, "n_nodes": 2, "n_llm_agent": 3,
         "tokens_agent": 500, "wall_s": 5.0, "reply": "他的父亲是工程师。"},
    ]
    out = tmp_path
    (out / "results.jsonl").write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in results), encoding="utf-8"
    )
    metrics = write_report(out)

    assert metrics["overall"]["n"] == 2
    assert abs(metrics["overall"]["hit@10"] - 0.5) < 1e-9
    saved = json.loads((out / "metrics.json").read_text(encoding="utf-8"))
    assert abs(saved["null_accuracy"] - 0.5) < 1e-9
    report = (out / "AGENT_REPORT.md").read_text(encoding="utf-8")
    assert "null" in report and "q4" in report  # 臆答的 null 题被点名


def test_write_report_empty_dir(tmp_path):
    assert write_report(tmp_path) == {}

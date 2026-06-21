"""读写事实筛选 prompt 解耦测试。

覆盖：purpose 分流、注册表、parse 一致性、覆盖正交、write_pipeline 集成。
"""

from __future__ import annotations

import pytest

from conftest import make_query_engine, MockLLM

from mcs.core.errors import LLMParseError
from mcs.core.plugin_manager import PluginContext, PluginManager
from mcs.core.query_engine import QueryEngine
from mcs.core.token_budget import TokenBudget
from mcs.core.write_pipeline import WritePipeline
from mcs.entities.config import MCSConfig
from mcs.entities.graph import Node
from mcs.interfaces.entry_plugin import EntryPluginInterface
from mcs.interfaces.llm import PromptBundle
from mcs.prompts import DEFAULT_PROMPTS
from mcs.prompts import select_facts


# === 辅助 ===


class _StaticEntry(EntryPluginInterface):
    """按 id 从图中返回静态节点列表的 entry 插件。"""

    def get_name(self) -> str:
        return "static_entry"

    def get_priority(self) -> int:
        return 100

    def __init__(self, node_ids: list[str], graph) -> None:
        self._ids = node_ids
        self._graph = graph

    def locate(self, query: str, ctx) -> list[Node]:
        return [
            n
            for n in (self._graph.get_node(i) for i in self._ids)
            if n is not None
        ]


def _fact_select_purposes(mock_llm) -> list[str]:
    """从 call_log 提取所有 select_facts* 调用的 purpose（按调用顺序）。"""
    return [
        call["purpose"]
        for call in mock_llm.call_log
        if call["purpose"].startswith("select_facts")
    ]


def _build_write_pipeline(store, mock_llm, *extra_plugins):
    """构造一个最小可用 WritePipeline（含 query_engine）。

    extra_plugins 注册到 query_engine 与 write_pipeline 共用的同一 pm，
    使阶段② 的种子定位（ENTRY 插件）与事实筛选都能被驱动。
    """
    pm = PluginManager()
    pm.register(mock_llm)
    for p in extra_plugins:
        pm.register(p)
    ctx = PluginContext(
        store=store,
        config=MCSConfig(),
        token_budget=TokenBudget(8000),
        context_renderer=None,  # type: ignore[arg-type]
        plugin_manager=pm,
    )
    pm.initialize_all(ctx)
    query_engine = QueryEngine(
        store=store,
        llm=mock_llm,
        plugin_manager=pm,
        token_budget=TokenBudget(8000),
        max_rounds=3,
        max_accumulated_nodes=20,
    )
    return WritePipeline(
        store=store,
        llm=mock_llm,
        query_engine=query_engine,
        plugin_manager=pm,
        token_budget=TokenBudget(8000),
        config=MCSConfig(),
    )


# === 4.1 query() 走 select_facts ===


def test_query_uses_select_facts(seeded_graph, mock_llm):
    """query() 的事实筛选 MUST 使用 purpose='select_facts'。"""
    mock_llm.set_response("select_nodes", [])
    mock_llm.set_response("select_facts", [])
    engine = make_query_engine(
        seeded_graph, mock_llm, _StaticEntry(["dl"], seeded_graph)
    )
    engine.query("什么是深度学习？")

    fact_purposes = _fact_select_purposes(mock_llm)
    assert fact_purposes, "query() 未触发任何 select_facts* 调用（测试可能空转）"
    assert all(p == "select_facts" for p in fact_purposes), (
        f"Expected all select_facts, got {fact_purposes}"
    )


# === 4.2 query_nodes() 走 select_facts_write ===


def test_query_nodes_uses_select_facts_write(seeded_graph, mock_llm):
    """query_nodes() 的事实筛选 MUST 使用 purpose='select_facts_write'。"""
    mock_llm.set_response("select_nodes", [])
    mock_llm.set_response("select_facts_write", [])
    engine = make_query_engine(
        seeded_graph, mock_llm, _StaticEntry(["dl"], seeded_graph)
    )
    engine.query_nodes("深度学习")

    fact_purposes = _fact_select_purposes(mock_llm)
    assert fact_purposes, "query_nodes() 未触发任何 select_facts* 调用（测试可能空转）"
    assert all(p == "select_facts_write" for p in fact_purposes), (
        f"Expected all select_facts_write, got {fact_purposes}"
    )


# === 4.3 DEFAULT_PROMPTS 注册与 parse 共享 ===


def test_select_facts_write_registered():
    """DEFAULT_PROMPTS 含 select_facts_write 条目。"""
    assert "select_facts_write" in DEFAULT_PROMPTS


def test_select_facts_write_parse_is_same_function():
    """select_facts_write 的 parse 与 select_facts 是同一个函数。"""
    bundle = DEFAULT_PROMPTS["select_facts_write"]
    assert bundle.parse is select_facts.parse


def test_select_facts_write_bundle_fields():
    """select_facts_write bundle 的 system 和 template 非空且与读侧不同。"""
    write_bundle = DEFAULT_PROMPTS["select_facts_write"]
    read_bundle = DEFAULT_PROMPTS["select_facts"]
    assert isinstance(write_bundle, PromptBundle)
    assert write_bundle.system
    assert write_bundle.template
    # 写侧 prompt 与读侧不同（窄召回 vs 宽召回）
    assert write_bundle.system != read_bundle.system
    assert write_bundle.template != read_bundle.template


# === 4.4 parse 边界一致性 ===


def test_parse_valid_array():
    """合法编号数组。"""
    assert select_facts.parse("[1, 3, 5]") == [1, 3, 5]


def test_parse_empty_array():
    """空数组 []。"""
    assert select_facts.parse("[]") == []


def test_parse_fenced():
    """含 markdown fence。"""
    assert select_facts.parse("```json\n[1, 2]\n```") == [1, 2]


def test_parse_non_array_raises():
    """非数组抛 LLMParseError。"""
    with pytest.raises(LLMParseError):
        select_facts.parse('"hello"')


def test_parse_non_int_raises():
    """非整数元素抛 LLMParseError。"""
    with pytest.raises(LLMParseError):
        select_facts.parse('[1, "two"]')


# === 4.5 覆盖正交 ===


def test_override_select_facts_does_not_affect_write():
    """覆盖 select_facts 不影响 select_facts_write。"""
    original_write = DEFAULT_PROMPTS["select_facts_write"]

    override = PromptBundle(
        system="override", template="override", parse=select_facts.parse
    )
    llm = MockLLM()
    llm.register_prompt("select_facts", override)

    # select_facts_write 不受影响
    assert llm.get_prompt("select_facts_write").system == original_write.system


def test_override_select_facts_write_does_not_affect_read():
    """覆盖 select_facts_write 不影响 select_facts。"""
    original_read = DEFAULT_PROMPTS["select_facts"]

    override = PromptBundle(
        system="override", template="override", parse=select_facts.parse
    )
    llm = MockLLM()
    llm.register_prompt("select_facts_write", override)

    # select_facts 不受影响
    assert llm.get_prompt("select_facts").system == original_read.system


# === 4.6 write_pipeline 阶段② 集成 ===


def test_write_pipeline_stage2_uses_select_facts_write(seeded_graph, mock_llm):
    """write_pipeline 阶段② 经 query_nodes → _traverse(select_facts_write)。

    真正穿过 write_pipeline.ingest()，断言阶段② 的事实筛选 purpose 为
    select_facts_write，且 ctx.related 经该路径产出（空命中也不阻塞后续阶段）。
    """
    mock_llm.set_response("select_nodes", [])
    mock_llm.set_response("select_facts_write", [])
    mock_llm.set_response("extract_concepts", [])  # 概念为空 → 跳过 ④⑤⑥

    wp = _build_write_pipeline(
        seeded_graph, mock_llm, _StaticEntry(["dl"], seeded_graph)
    )
    wctx = wp.ingest("深度学习")

    fact_purposes = _fact_select_purposes(mock_llm)
    assert fact_purposes, "write_pipeline 阶段② 未触发 select_facts* 调用"
    assert all(p == "select_facts_write" for p in fact_purposes), (
        f"Expected all select_facts_write, got {fact_purposes}"
    )
    # ctx.related 经 select_facts_write 路径产出、是 list
    assert isinstance(wctx.related, list)


def test_query_nodes_empty_result_no_crash(seeded_graph, mock_llm):
    """窄召回返回空结果时，query_nodes 不崩溃，返回空列表。"""
    mock_llm.set_response("select_nodes", [])
    mock_llm.set_response("select_facts_write", [])

    engine = make_query_engine(
        seeded_graph, mock_llm, _StaticEntry(["dl"], seeded_graph)
    )
    result = engine.query_nodes("不存在的内容")
    assert result is not None
    assert isinstance(result, list)

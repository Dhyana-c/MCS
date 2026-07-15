# -*- coding: utf-8 -*-
"""alias 毒化防线测试（回归：agent 建图曾把 LLM 的对象别名写进图，
崩掉 AliasIndexPlugin.build → load-on-startup 吞异常 → 关键词检索静默报废）。

三层防线：
1. 解析规范化：judge_relations parse 把 aliases_to_add 收口为 list[str]
2. 写入闸门：_dispatch_merge 拒绝非 str 别名进 extensions
3. 读取防御：alias_index add_entry 跳过非 str / deserialize 过滤（历史毒化自愈）
"""

import json

from mcs.core.plugin_manager import PluginManager
from mcs.core.query_engine import QueryEngine
from mcs.core.token_budget import TokenBudget
from mcs.core.write_pipeline import WritePipeline
from mcs.entities.decisions import ConceptDraft, Decision
from mcs.entities.graph import CLASS_CONCEPT, Node
from mcs.plugins.index.alias_index import AliasIndexPlugin
from mcs.prompts.judge_relations import parse as judge_parse


# ---------- 1. 解析规范化 ----------


def test_judge_parse_normalizes_alias_objects():
    """LLM 把别名写成对象（混淆 edges_to_names 格式）→ 取字符串值兜底；杂类丢弃。"""
    raw = json.dumps([{
        "action": "merge", "concept_name": "Christian McCaffrey", "target_id": "n1",
        "aliases_to_add": [
            "CMC",                              # 正常 str
            {"target_name": "King Henry"},      # 对象 → 取值兜底
            {"alias": "  Stafford  "},          # 对象 + 空白 → strip
            123,                                # 非法类型 → 丢弃
            "",                                 # 空串 → 丢弃
            {"x": None},                        # 无字符串值 → 丢弃
        ],
    }])
    decisions = judge_parse(raw)
    assert len(decisions) == 1
    assert decisions[0].aliases_to_add == ["CMC", "King Henry", "Stafford"]


def test_judge_parse_aliases_all_strings_unchanged():
    raw = json.dumps([{
        "action": "merge", "concept_name": "A", "target_id": "n1",
        "aliases_to_add": ["a1", "a2"],
    }])
    assert judge_parse(raw)[0].aliases_to_add == ["a1", "a2"]


# ---------- 2. 写入闸门 ----------


def test_dispatch_merge_rejects_non_str_alias(empty_graph, mock_llm):
    """即使 Decision 被程序化构造塞进 dict 别名，写入侧也不放行。"""
    empty_graph.add_node(Node(id="n1", name="Brock Purdy", content="四分卫",
                              node_class=CLASS_CONCEPT))
    pm = PluginManager()
    pm.register(mock_llm)
    tb = TokenBudget(8000)
    qe = QueryEngine(store=empty_graph, llm=mock_llm, plugin_manager=pm, token_budget=tb)
    wp = WritePipeline(store=empty_graph, llm=mock_llm, query_engine=qe,
                       plugin_manager=pm, token_budget=tb)
    decision = Decision(
        action="merge", target_id="n1",
        concept=ConceptDraft(name="Purdy", content=""),
        aliases_to_add=[{"target_name": "Mr. Irrelevant"}, "MrI"],  # type: ignore[list-item]
    )
    wp._dispatch_merge(decision)
    aliases = empty_graph.get_node("n1").extensions["alias_index"]["aliases"]
    assert all(isinstance(a, str) for a in aliases)
    assert "MrI" in aliases and "Purdy" in aliases


# ---------- 3. 读取防御 ----------


def _poisoned_node() -> Node:
    return Node(
        id="p1", name="Derrick Henry", content="跑卫", node_class=CLASS_CONCEPT,
        extensions={"alias_index": {"aliases": ["King Henry", {"target_name": "KH"}]}},
    )


def test_alias_index_add_entry_skips_non_str_no_raise():
    plugin = AliasIndexPlugin()
    plugin.add_entry(_poisoned_node())  # 不抛
    assert "p1" in plugin.index.get("King Henry", set())
    assert "p1" in plugin.index.get("Derrick Henry", set())
    # dict 别名被跳过、不产生任何不可哈希键
    assert all(isinstance(k, str) for k in plugin.index)


def test_alias_index_build_survives_poisoned_node():
    """一条毒化数据不报废全图索引（load-on-startup 场景）。"""

    class _Store:
        def get_all_nodes(self):
            return [
                _poisoned_node(),
                Node(id="ok", name="Matthew Stafford", content="",
                     node_class=CLASS_CONCEPT),
            ]

    plugin = AliasIndexPlugin()
    plugin.build(_Store())  # 不抛
    assert "ok" in plugin.index.get("Matthew Stafford", set())


def test_alias_index_deserialize_filters_non_str():
    plugin = AliasIndexPlugin()
    got = plugin.deserialize({"aliases": ["A", {"target_name": "B"}, 3, "C"]})
    assert got == {"aliases": ["A", "C"]}
    assert plugin.deserialize({}) == {"aliases": []}
    assert plugin.deserialize(None) == {"aliases": []}

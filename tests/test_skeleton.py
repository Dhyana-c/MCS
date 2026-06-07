"""项目骨架在新的统一工作流上的冒烟测试。

验证：

(a) 所有 ``mcs.*`` 子包和模块可导入。
(b) 带抽象方法的接口直接实例化时抛出 ``TypeError``。
(c) ``Source`` 数据类位于 ``mcs.plugins.phase1.source_tracking``，
    而非 ``mcs.core.graph``。
(d) Phase 1 插件类的 ``name`` 类属性与设计一致。
(e) 结构健全性（Node 字段、QueryContext / WriteContext 字段、
    默认配置插件、ContextRenderer.get_summary 回退行为）。
"""

from __future__ import annotations

import importlib
from dataclasses import fields

import pytest

# 在全新检出时必须可导入的模块。
ALL_MODULES = [
    "mcs",
    # core
    "mcs.core",
    "mcs.core.builder",
    "mcs.core.config",
    "mcs.core.context_renderer",
    "mcs.core.decisions",
    "mcs.core.errors",
    "mcs.core.graph",
    "mcs.core.mcs",
    "mcs.core.plugin_manager",
    "mcs.core.query_engine",
    "mcs.core.token_budget",
    "mcs.core.write_pipeline",
    # interfaces (5 new plugin chains + 6 carried over from skeleton)
    "mcs.interfaces",
    "mcs.interfaces.arbitration_plugin",
    "mcs.interfaces.compaction_plugin",
    "mcs.interfaces.entry_plugin",
    "mcs.interfaces.index",
    "mcs.interfaces.llm",
    "mcs.interfaces.maintenance",
    "mcs.interfaces.node_extension",
    "mcs.interfaces.postprocess_plugin",
    "mcs.interfaces.storage_schema_ext",
    "mcs.interfaces.trim_plugin",
    # plugins
    "mcs.plugins",
    "mcs.core.plugin",
    "mcs.plugins.phase1",
    "mcs.plugins.phase1.alias_index",
    "mcs.plugins.phase1.claude_llm",
    "mcs.plugins.phase1.deepseek_llm",
    "mcs.plugins.phase1.fanout_reducer",
    "mcs.plugins.phase1.hub_fallback",
    "mcs.plugins.phase1.priority_trim",
    "mcs.plugins.phase1.source_tracking",
    "mcs.plugins.phase1.summary",
    "mcs.plugins.phase1.summary_regen",
    "mcs.plugins.phase2",
    "mcs.plugins.phase2.arbitration",
    "mcs.plugins.phase2.confidence",
    "mcs.plugins.phase2.event_layer",
    "mcs.plugins.phase2.gc",
    "mcs.plugins.phase2.timeseries_entry",
    "mcs.plugins.phase2.versioning",
    # presets
    "mcs.presets",
    "mcs.presets.phase1",
    # prompts (9 purposes + registry)
    "mcs.prompts",
    "mcs.prompts.arbitrate",
    "mcs.prompts.decide_directions",
    "mcs.prompts.decide_hub",
    "mcs.prompts.extract_concepts",
    "mcs.prompts.gen_aliases",
    "mcs.prompts.gen_summary",
    "mcs.prompts.judge_relations",
    "mcs.prompts.navigate_hub",
    "mcs.prompts.synthesize",
    # utils
    "mcs.utils",
    "mcs.utils.text_utils",
    "mcs.utils.tokenizer",
]


# === (a) 所有子包可导入 ===


@pytest.mark.parametrize("module_path", ALL_MODULES)
def test_module_importable(module_path: str) -> None:
    importlib.import_module(module_path)


# === (b) ABC 接口 ===


def test_abc_interfaces_not_instantiable() -> None:
    """带抽象方法的接口不能直接实例化。"""
    from mcs.interfaces.arbitration_plugin import ArbitrationPluginInterface
    from mcs.interfaces.compaction_plugin import CompactionPluginInterface
    from mcs.interfaces.entry_plugin import EntryPluginInterface
    from mcs.interfaces.index import IndexInterface
    from mcs.interfaces.llm import LLMInterface
    from mcs.interfaces.maintenance import MaintenanceInterface
    from mcs.interfaces.node_extension import NodeExtensionInterface
    from mcs.interfaces.postprocess_plugin import PostprocessPluginInterface
    from mcs.interfaces.storage_schema_ext import StorageSchemaExtensionInterface
    from mcs.interfaces.trim_plugin import TrimPluginInterface
    from mcs.core.store import StoreInterface

    for interface_cls in [
        ArbitrationPluginInterface,
        CompactionPluginInterface,
        EntryPluginInterface,
        IndexInterface,
        LLMInterface,
        MaintenanceInterface,
        NodeExtensionInterface,
        PostprocessPluginInterface,
        StorageSchemaExtensionInterface,
        TrimPluginInterface,
        StoreInterface,
    ]:
        with pytest.raises(TypeError):
            interface_cls()  # type: ignore[abstract]


# === (c) Source 位置 ===


def test_source_lives_in_plugin_not_core() -> None:
    from mcs.plugins.phase1.source_tracking import Source

    assert Source is not None

    import mcs.core.graph as core_graph

    assert not hasattr(core_graph, "Source"), (
        "Source 不能从 mcs.core.graph 导出"
        "（它属于 SourceTrackingPlugin）。"
    )


# === (d) 插件 name 属性 ===


def test_plugin_names_match_design() -> None:
    """每个 Phase 1 插件类都有默认配置和测试所期望的 ``get_name()`` 方法。"""
    from mcs.plugins.phase1.alias_index import (
        AliasEntryPlugin,
        AliasIndexPlugin,
    )
    from mcs.plugins.phase1.claude_llm import ClaudeLLMPlugin
    from mcs.plugins.phase1.deepseek_llm import DeepSeekLLMPlugin
    from mcs.plugins.phase1.fanout_reducer import FanoutReducerPlugin
    from mcs.plugins.phase1.hub_fallback import HubFallbackEntryPlugin
    from mcs.plugins.phase1.priority_trim import PriorityTrimPlugin
    from mcs.plugins.phase1.source_tracking import (
        IdempotencyCheckPlugin,
        SourceTrackingPlugin,
    )
    from mcs.plugins.phase1.summary import SummaryPlugin
    from mcs.plugins.phase1.summary_regen import SummaryRegenPlugin

    assert AliasIndexPlugin().get_name() == "alias_index"
    assert AliasEntryPlugin().get_name() == "alias_entry"
    assert HubFallbackEntryPlugin().get_name() == "hub_fallback"
    assert PriorityTrimPlugin().get_name() == "priority_trim"
    assert SummaryPlugin().get_name() == "summary"
    assert SourceTrackingPlugin().get_name() == "source_tracking"
    assert IdempotencyCheckPlugin().get_name() == "idempotency_check"
    assert FanoutReducerPlugin().get_name() == "fanout_reducer"
    assert SummaryRegenPlugin().get_name() == "summary_regen"
    assert DeepSeekLLMPlugin().get_name() == "deepseek_llm"
    assert ClaudeLLMPlugin().get_name() == "claude_llm"


def test_alias_entry_plugin_priority() -> None:
    """AliasEntryPlugin 必须声明 get_priority()=100, exclusive=False。"""
    from mcs.plugins.phase1.alias_index import AliasEntryPlugin

    p = AliasEntryPlugin()
    assert p.get_priority() == 100
    assert p.exclusive is False


# === (e) 结构健全性 ===


def test_node_has_only_minimal_core_fields() -> None:
    from mcs.core.graph import Node

    field_names = {f.name for f in fields(Node)}
    expected = {"id", "name", "content", "role", "extensions"}
    assert field_names == expected, (
        f"Node has unexpected fields: {field_names ^ expected}"
    )


def test_query_context_has_4_lifecycle_fields() -> None:
    """QueryContext：system_prompt / user_input / intermediate / result_set + metadata。"""
    from mcs.core.query_engine import QueryContext

    field_names = {f.name for f in fields(QueryContext)}
    expected = {
        "system_prompt",
        "user_input",
        "intermediate",
        "result_set",
        "metadata",
    }
    assert field_names == expected, (
        f"QueryContext fields mismatch: {field_names ^ expected}"
    )


def test_write_context_has_7_lifecycle_fields() -> None:
    """WriteContext：system_prompt, user_input, processed, related, concepts,
    decisions, changed（+ metadata + skip 控制标志）。"""
    from mcs.core.write_pipeline import WriteContext

    field_names = {f.name for f in fields(WriteContext)}
    expected_core = {
        "system_prompt",
        "user_input",
        "processed",
        "related",
        "concepts",
        "decisions",
        "changed",
    }
    assert expected_core.issubset(field_names), (
        f"WriteContext missing core fields: {expected_core - field_names}"
    )


def test_decision_action_types() -> None:
    """Decision 数据类必须接受四种文档化的 action 类型。"""
    from mcs.core.decisions import ConceptDraft, Decision

    c = ConceptDraft(name="X", content="...")
    Decision(action="merge", concept=c, target_id="n1")
    Decision(action="create", concept=c, edges_to=["n2"])
    Decision(action="attach_statement", target_id="n1", statement="...")
    Decision(action="no_op", concept=c, reason="not relevant")


def test_default_phase1_config_plugins() -> None:
    """默认 Phase 1 插件列表符合 phase1-defaults 规范。"""
    from mcs.core.config import (
        PHASE1_DEFAULT_PLUGINS,
        PHASE1_SHARED_PLUGINS,
        PHASE1_WRITE_PLUGINS,
        PHASE1_READ_PLUGINS,
        MCSConfig,
    )

    config = MCSConfig.knowledge_graph()
    # 验证分离后的插件列表
    assert config.shared_plugins == PHASE1_SHARED_PLUGINS
    assert config.write_plugins == PHASE1_WRITE_PLUGINS
    assert config.read_plugins == PHASE1_READ_PLUGINS
    assert config.token_budget == 8000
    assert config.max_rounds == 5
    assert config.max_picked == 50

    # 健全性检查：按规范应有 10 个插件（移除了 sqlite_storage，它不是插件）
    # shared: source_tracking, summary (2)
    # write: idempotency_check, fanout_reducer, summary_regen (3)
    # read: alias_index, alias_entry, hub_fallback, priority_trim (4)
    # total: 2 + 3 + 4 = 9 个插件
    assert len(PHASE1_SHARED_PLUGINS) == 2
    assert len(PHASE1_WRITE_PLUGINS) == 3
    assert len(PHASE1_READ_PLUGINS) == 4
    assert len(PHASE1_DEFAULT_PLUGINS) == 9

    assert "alias_entry" in PHASE1_READ_PLUGINS
    assert "hub_fallback" in PHASE1_READ_PLUGINS
    assert "priority_trim" in PHASE1_READ_PLUGINS
    assert "idempotency_check" in PHASE1_WRITE_PLUGINS
    assert "fanout_reducer" in PHASE1_WRITE_PLUGINS
    assert "summary_regen" in PHASE1_WRITE_PLUGINS
    assert "source_tracking" in PHASE1_SHARED_PLUGINS
    assert "summary" in PHASE1_SHARED_PLUGINS


def test_context_renderer_get_summary_fallback() -> None:
    """ContextRenderer.get_summary：读取 extension；回退到 content[:200]。"""
    from mcs.core.context_renderer import ContextRenderer
    from mcs.core.graph import Node

    node = Node(id="n1", name="X", content="hello world", role="concept")
    assert ContextRenderer.get_summary(node) == "hello world"

    node_with_summary = Node(
        id="n2",
        name="Y",
        content="long content",
        role="concept",
        extensions={"summary": {"text": "short summary"}},
    )
    assert ContextRenderer.get_summary(node_with_summary) == "short summary"


def test_default_prompts_has_9_purposes() -> None:
    """DEFAULT_PROMPTS 注册了全部 9 个 Phase 1 目的。"""
    from mcs.prompts import DEFAULT_PROMPTS

    expected_purposes = {
        "extract_concepts",
        "judge_relations",
        "decide_directions",
        "decide_hub",
        "navigate_hub",
        "arbitrate",
        "synthesize",
        "gen_aliases",
        "gen_summary",
    }
    assert set(DEFAULT_PROMPTS.keys()) == expected_purposes


def test_plugin_manager_arbitration_singleton() -> None:
    """注册第二个 ArbitrationPlugin 必须抛出 ConfigurationError。"""
    from mcs.core.errors import ConfigurationError
    from mcs.core.plugin_manager import PluginManager
    from mcs.core.plugin import PluginType
    from mcs.interfaces.arbitration_plugin import ArbitrationPluginInterface

    class FakeArb(ArbitrationPluginInterface):
        def get_name(self) -> str:
            return "fake_arb_1"

        def arbitrate(self, accumulated, query, ctx):
            return accumulated

    class FakeArb2(FakeArb):
        def get_name(self) -> str:
            return "fake_arb_2"

    pm = PluginManager()
    pm.register(FakeArb())
    with pytest.raises(ConfigurationError):
        pm.register(FakeArb2())


def test_plugin_manager_entry_plugin_priority_sort() -> None:
    """get_all(PluginType.ENTRY) 返回按优先级排序的列表。"""
    from mcs.core.plugin_manager import PluginManager
    from mcs.core.plugin import PluginType
    from mcs.interfaces.entry_plugin import EntryPluginInterface

    class FakeEntry(EntryPluginInterface):
        def locate(self, query, ctx):
            return []

    class High(FakeEntry):
        def get_name(self) -> str:
            return "high"

        def get_priority(self) -> int:
            return 100

    class Low(FakeEntry):
        def get_name(self) -> str:
            return "low"

        def get_priority(self) -> int:
            return 0

    class Mid(FakeEntry):
        def get_name(self) -> str:
            return "mid"

        def get_priority(self) -> int:
            return 50

    pm = PluginManager()
    pm.register(Low())
    pm.register(High())
    pm.register(Mid())

    sorted_plugins = pm.get_all(PluginType.ENTRY)
    assert [p.get_name() for p in sorted_plugins] == ["high", "mid", "low"]

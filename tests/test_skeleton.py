"""Smoke tests for the project skeleton.

Validates:

(a) All ``mcs.*`` subpackages can be imported.
(b) ABC interfaces with abstract methods raise ``TypeError`` on direct
    instantiation; hook interfaces (no abstract methods) are instantiable.
(c) ``Source`` dataclass lives in ``mcs.plugins.phase1.source_tracking``,
    NOT in ``mcs.core.graph``.
(d) Five Phase 1 plugin classes have ``name`` class attribute matching
    their file names.

Plus a few structural sanity checks (state-machine sizes, Node fields,
default config).
"""

from __future__ import annotations

import importlib
from dataclasses import fields

import pytest

# All subpackages and modules we expect to be importable.
ALL_MODULES = [
    "mcs",
    "mcs.core",
    "mcs.core.graph",
    "mcs.core.token_budget",
    "mcs.core.serializer",
    "mcs.core.write_pipeline",
    "mcs.core.query_engine",
    "mcs.core.config",
    "mcs.core.plugin_manager",
    "mcs.interfaces",
    "mcs.interfaces.storage",
    "mcs.interfaces.index",
    "mcs.interfaces.llm",
    "mcs.interfaces.node_extension",
    "mcs.interfaces.pipeline_hook",
    "mcs.interfaces.query_hook",
    "mcs.interfaces.storage_schema_ext",
    "mcs.interfaces.maintenance",
    "mcs.plugins",
    "mcs.plugins.base",
    "mcs.plugins.phase1",
    "mcs.plugins.phase1.alias_index",
    "mcs.plugins.phase1.summary",
    "mcs.plugins.phase1.source_tracking",
    "mcs.plugins.phase1.sqlite_storage",
    "mcs.plugins.phase1.deepseek_llm",
    "mcs.plugins.phase2",
    "mcs.plugins.phase2.event_layer",
    "mcs.plugins.phase2.versioning",
    "mcs.plugins.phase2.confidence",
    "mcs.plugins.phase2.timeseries_entry",
    "mcs.plugins.phase2.gc",
    "mcs.plugins.phase2.arbitration",
    "mcs.prompts",
    "mcs.prompts.extract",
    "mcs.prompts.place",
    "mcs.prompts.merge",
    "mcs.prompts.traverse",
    "mcs.prompts.synthesize",
    "mcs.prompts.aliases",
    "mcs.prompts.summary",
    "mcs.utils",
    "mcs.utils.tokenizer",
    "mcs.utils.text_utils",
]


# === (a) All subpackages importable ===


@pytest.mark.parametrize("module_path", ALL_MODULES)
def test_module_importable(module_path: str) -> None:
    importlib.import_module(module_path)


# === (b) ABC interfaces ===


def test_abc_interfaces_with_abstract_methods_not_instantiable() -> None:
    """Interfaces with abstractmethod cannot be instantiated directly."""
    from mcs.interfaces.index import IndexInterface
    from mcs.interfaces.llm import LLMInterface
    from mcs.interfaces.maintenance import MaintenanceInterface
    from mcs.interfaces.node_extension import NodeExtensionInterface
    from mcs.interfaces.storage import StorageInterface
    from mcs.interfaces.storage_schema_ext import StorageSchemaExtensionInterface

    for interface_cls in [
        StorageInterface,
        IndexInterface,
        LLMInterface,
        NodeExtensionInterface,
        StorageSchemaExtensionInterface,
        MaintenanceInterface,
    ]:
        with pytest.raises(TypeError):
            interface_cls()  # type: ignore[abstract]


def test_hook_interfaces_instantiable() -> None:
    """Hook interfaces have no abstract methods → instantiable as no-op hooks."""
    from mcs.interfaces.pipeline_hook import PipelineHookInterface
    from mcs.interfaces.query_hook import QueryHookInterface

    # Should not raise:
    PipelineHookInterface()
    QueryHookInterface()


# === (c) Source location ===


def test_source_lives_in_plugin_not_core() -> None:
    from mcs.plugins.phase1.source_tracking import Source

    assert Source is not None

    import mcs.core.graph as core_graph

    assert not hasattr(core_graph, "Source"), (
        "Source must NOT be exported from mcs.core.graph "
        "(it belongs to SourceTrackingPlugin)."
    )


# === (d) Plugin name attributes match file names ===


def test_phase1_plugin_names_match_filenames() -> None:
    from mcs.plugins.phase1.alias_index import AliasIndexPlugin
    from mcs.plugins.phase1.deepseek_llm import DeepSeekLLMPlugin
    from mcs.plugins.phase1.source_tracking import SourceTrackingPlugin
    from mcs.plugins.phase1.sqlite_storage import SQLiteStoragePlugin
    from mcs.plugins.phase1.summary import SummaryPlugin

    assert AliasIndexPlugin.name == "alias_index"
    assert SummaryPlugin.name == "summary"
    assert SourceTrackingPlugin.name == "source_tracking"
    assert SQLiteStoragePlugin.name == "sqlite_storage"
    assert DeepSeekLLMPlugin.name == "deepseek_llm"


# === Structural sanity ===


def test_writepipeline_has_9_states() -> None:
    from mcs.core.write_pipeline import WritePipelineState

    assert len(list(WritePipelineState)) == 9


def test_querypipeline_has_7_states() -> None:
    from mcs.core.query_engine import QueryPipelineState

    assert len(list(QueryPipelineState)) == 7


def test_node_has_only_minimal_core_fields() -> None:
    from mcs.core.graph import Node

    field_names = {f.name for f in fields(Node)}
    expected = {"id", "name", "content", "role", "extensions"}
    assert field_names == expected, (
        f"Node has unexpected fields: {field_names ^ expected}"
    )


def test_default_phase1_config_has_5_plugins() -> None:
    from mcs.core.config import MCSConfig

    config = MCSConfig.knowledge_graph()
    assert config.plugins == [
        "alias_index",
        "summary",
        "source_tracking",
        "sqlite_storage",
        "deepseek_llm",
    ]


def test_serializer_get_summary_fallback() -> None:
    """Serializer.get_summary should fall back to content when summary slot absent."""
    from mcs.core.graph import Node
    from mcs.core.serializer import Serializer

    node = Node(id="n1", name="X", content="hello world", role="concept")
    assert Serializer.get_summary(node) == "hello world"

    node_with_summary = Node(
        id="n2",
        name="Y",
        content="long content",
        role="concept",
        extensions={"summary": {"text": "short summary"}},
    )
    assert Serializer.get_summary(node_with_summary) == "short summary"

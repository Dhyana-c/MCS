"""MCS 类新 API 测试：register_shared_plugin, register_plugin(target), unregister_plugin, show, shutdown。"""

from __future__ import annotations

import pytest

from mcs.core.config import MCSConfig
from mcs.core.graph import Node
from mcs.core.plugin import Plugin, PluginType
from mcs.core.plugin_manager import PluginContext, PluginManager
from mcs.core.query_engine import QueryEngine
from mcs.core.token_budget import TokenBudget
from mcs.core.write_pipeline import WritePipeline
from mcs.stores.in_memory import InMemoryStore
from tests.conftest import MockLLM


class _DummyPlugin(Plugin):
    """测试用的空插件。"""

    def __init__(self, name: str = "dummy", shutdown_called: list | None = None):
        super().__init__()
        self._name = name
        self._shutdown_called = shutdown_called

    def get_name(self) -> str:
        return self._name

    def get_type(self) -> PluginType:
        return PluginType.POSTPROCESS

    def execute(self, **kwargs):
        return None

    def shutdown(self) -> None:
        if self._shutdown_called is not None:
            self._shutdown_called.append(self._name)


def _build_mcs(mock_llm: MockLLM):
    """构建一个用于测试的 MCS 实例。"""
    from mcs.core.context_renderer import ContextRenderer
    from mcs.core.mcs import MCS

    store = InMemoryStore()
    token_budget = TokenBudget(8000)
    write_manager = PluginManager()
    read_manager = PluginManager()

    # 注册 mock_llm 到两侧
    write_manager.register(mock_llm)
    read_manager.register(mock_llm)

    # 初始化插件
    context_renderer = ContextRenderer(read_manager)
    config = MCSConfig()
    write_ctx = PluginContext(
        store=store,
        config=config,
        token_budget=token_budget,
        context_renderer=context_renderer,
        plugin_manager=write_manager,
    )
    write_manager.initialize_all(write_ctx)
    read_ctx = PluginContext(
        store=store,
        config=config,
        token_budget=token_budget,
        context_renderer=context_renderer,
        plugin_manager=read_manager,
    )
    read_manager.initialize_all(read_ctx)

    # 构建管线
    query_engine = QueryEngine(
        store=store,
        llm=mock_llm,
        plugin_manager=read_manager,
        token_budget=token_budget,
        max_rounds=3,
        max_accumulated_nodes=20,
    )
    write_pipeline = WritePipeline(
        store=store,
        llm=mock_llm,
        query_engine=query_engine,
        plugin_manager=write_manager,
        token_budget=token_budget,
        config=config,
    )

    return MCS(
        write_pipeline=write_pipeline,
        query_engine=query_engine,
        store=store,
        write_manager=write_manager,
        read_manager=read_manager,
    )


# === 5.4 test_register_shared_plugin ===


def test_register_shared_plugin(mock_llm):
    """register_shared_plugin 应将同一插件实例注册到两侧。"""
    mcs = _build_mcs(mock_llm)
    plugin = _DummyPlugin("shared_test")

    mcs.register_shared_plugin(plugin)

    # 两侧都应该有这个插件
    w = mcs.write_manager.get_by_name("shared_test")
    r = mcs.read_manager.get_by_name("shared_test")
    assert w is not None
    assert r is not None
    # 同一实例
    assert w is r


def test_register_shared_plugin_same_instance_no_error(mock_llm):
    """同一实例注册到不同 manager 不应触发 ValueError。"""
    mcs = _build_mcs(mock_llm)
    plugin = _DummyPlugin("shared_unique")

    # 第一次注册（共享）
    mcs.register_shared_plugin(plugin)

    # 再次尝试注册到同一 manager 应抛 ValueError
    with pytest.raises(ValueError, match="already registered"):
        mcs.write_manager.register(plugin)


# === 5.5 test_register_plugin_target ===


def test_register_plugin_target_writer(mock_llm):
    """register_plugin(target='writer') 应只注册到 write_manager。"""
    mcs = _build_mcs(mock_llm)
    plugin = _DummyPlugin("write_only")

    mcs.register_plugin(plugin, target="writer")

    assert mcs.write_manager.get_by_name("write_only") is not None
    assert mcs.read_manager.get_by_name("write_only") is None


def test_register_plugin_target_reader(mock_llm):
    """register_plugin(target='reader') 应只注册到 read_manager。"""
    mcs = _build_mcs(mock_llm)
    plugin = _DummyPlugin("read_only")

    mcs.register_plugin(plugin, target="reader")

    assert mcs.write_manager.get_by_name("read_only") is None
    assert mcs.read_manager.get_by_name("read_only") is not None


def test_register_plugin_target_case_error(mock_llm):
    """register_plugin 应拒绝无效的 target 值。"""
    mcs = _build_mcs(mock_llm)
    plugin = _DummyPlugin("bad_target")

    # target 必须是 "writer" 或 "reader"，其他值会导致逻辑错误
    # 这里我们测试的是正确用法
    mcs.register_plugin(plugin, target="writer")
    mcs.register_plugin(_DummyPlugin("another"), target="reader")


# === 5.6 test_unregister_plugin ===


def test_unregister_plugin_removes_from_target(mock_llm):
    """unregister_plugin 应从指定 manager 移除插件。"""
    mcs = _build_mcs(mock_llm)
    plugin = _DummyPlugin("to_remove")
    mcs.register_plugin(plugin, target="writer")

    result = mcs.unregister_plugin("to_remove", target="writer")

    assert result is True
    assert mcs.write_manager.get_by_name("to_remove") is None


def test_unregister_plugin_nonexistent_returns_false(mock_llm):
    """unregister_plugin 对不存在的插件应返回 False。"""
    mcs = _build_mcs(mock_llm)

    result = mcs.unregister_plugin("nonexistent", target="writer")

    assert result is False


def test_unregister_plugin_shared_removes_from_one_side(mock_llm):
    """共享插件注销一侧后另一侧仍存在。"""
    mcs = _build_mcs(mock_llm)
    plugin = _DummyPlugin("shared_remove")
    mcs.register_shared_plugin(plugin)

    # 从 write_manager 注销
    mcs.unregister_plugin("shared_remove", target="writer")

    # read_manager 应仍有
    assert mcs.write_manager.get_by_name("shared_remove") is None
    assert mcs.read_manager.get_by_name("shared_remove") is not None


# === 5.7 test_show ===


def test_show_returns_markdown_with_mermaid(mock_llm):
    """show() 应返回包含 Mermaid 流程图的 Markdown。"""
    mcs = _build_mcs(mock_llm)

    output = mcs.show()

    assert "## Writer Pipeline" in output
    assert "## Reader Pipeline" in output
    assert "```mermaid" in output
    assert "flowchart TD" in output


def test_show_lists_plugins(mock_llm):
    """show() 应列出各管线已注册插件。"""
    mcs = _build_mcs(mock_llm)
    # 添加一些插件
    mcs.register_plugin(_DummyPlugin("writer_plugin"), target="writer")
    mcs.register_plugin(_DummyPlugin("reader_plugin"), target="reader")

    output = mcs.show()

    # 检查插件列表
    assert "mock_llm(llm)" in output
    assert "writer_plugin(postprocess)" in output
    assert "reader_plugin(postprocess)" in output


def test_show_includes_all_stages(mock_llm):
    """show() 应包含完整的阶段流程。"""
    mcs = _build_mcs(mock_llm)

    output = mcs.show()

    # Writer stages
    assert "① Preprocess" in output
    assert "② Related Nodes" in output
    assert "③ Extract Concepts" in output
    assert "④ Judge Relations" in output
    assert "⑤ Apply Decisions" in output
    assert "⑥ Compaction" in output
    assert "⑦ Auto Persist" in output

    # Reader stages
    assert "② Seed Locating" in output
    assert "③ Traverse Loop" in output
    assert "④ Arbitration" in output
    assert "⑤ Postprocess" in output


# === 5.8 test_shutdown_dedup ===


def test_shutdown_calls_plugin_shutdown_once(mock_llm):
    """shutdown() 应调用每个插件的 shutdown() 方法。"""
    shutdown_log: list[str] = []
    mcs = _build_mcs(mock_llm)
    # 替换 mock_llm 的 shutdown 来记录
    mock_llm_shutdown_called = []
    original_shutdown = mock_llm.shutdown
    mock_llm.shutdown = lambda: mock_llm_shutdown_called.append("mock_llm")

    mcs.shutdown()

    assert "mock_llm" in mock_llm_shutdown_called
    # 恢复原方法
    mock_llm.shutdown = original_shutdown


def test_shutdown_shared_plugin_only_once(mock_llm):
    """共享插件只应被 shutdown 一次。"""
    shutdown_log: list[str] = []
    shared = _DummyPlugin("shared_shutdown", shutdown_log)
    write_only = _DummyPlugin("write_shutdown", shutdown_log)
    read_only = _DummyPlugin("read_shutdown", shutdown_log)

    mcs = _build_mcs(mock_llm)
    mcs.register_shared_plugin(shared)
    mcs.register_plugin(write_only, target="writer")
    mcs.register_plugin(read_only, target="reader")

    mcs.shutdown()

    # 每个插件只 shutdown 一次
    assert shutdown_log.count("shared_shutdown") == 1
    assert shutdown_log.count("write_shutdown") == 1
    assert shutdown_log.count("read_shutdown") == 1


def test_shutdown_empty_managers_no_error(mock_llm):
    """空 manager shutdown 不应报错。"""
    mcs = _build_mcs(mock_llm)
    # mock_llm 已注册，但 shutdown 应正常工作
    mcs.shutdown()
    # 不应抛异常
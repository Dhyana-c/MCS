"""插件链组合规则测试。

读查询编排退役后（见 retire-framework-query-pipeline），ARBITRATION / POSTPROCESS /
QUERY_PREPROCESS 三类插件与对应 PluginType 已删——本文件仅覆盖存活的 ENTRY / TRIM /
WRITE_PREPROCESS 链规则。
"""

from __future__ import annotations

from typing import Any

from mcs.core.plugin import PluginType
from mcs.core.plugin_manager import PluginManager
from mcs.entities.graph import Node
from mcs.interfaces.entry_plugin import EntryPluginInterface
from mcs.interfaces.write_preprocess_plugin import WritePreprocessPluginInterface

# === EntryPlugin 优先级排序 ===


class _Entry(EntryPluginInterface):
    def locate(self, query: str, ctx: Any) -> list[Node]:
        return []


class _High(_Entry):
    def get_name(self) -> str:
        return "high"

    def get_priority(self) -> int:
        return 100


class _Mid(_Entry):
    def get_name(self) -> str:
        return "mid"

    def get_priority(self) -> int:
        return 50


class _Low(_Entry):
    def get_name(self) -> str:
        return "low"

    def get_priority(self) -> int:
        return 0


def test_entry_plugins_returned_in_priority_descending():
    pm = PluginManager()
    pm.register(_Low())
    pm.register(_High())
    pm.register(_Mid())
    plugins = pm.get_all(PluginType.ENTRY)
    assert [p.get_name() for p in plugins] == ["high", "mid", "low"]


def test_entry_plugin_default_priority_is_zero():
    class _Default(_Entry):
        def get_name(self) -> str:
            return "default"

    p = _Default()
    assert p.get_priority() == 0
    assert p.exclusive is False


def test_entry_plugin_exclusive_attribute():
    class _Excl(_Entry):
        def get_name(self) -> str:
            return "ex"

        def get_priority(self) -> int:
            return 50

        @property
        def exclusive(self) -> bool:
            return True

    p = _Excl()
    assert p.exclusive is True


# === WritePreprocess 插件类型 ===


def test_write_preprocess_plugin_type_registered_and_found():
    """WritePreprocessPlugin 注册后可通过 PluginType.WRITE_PREPROCESS 查找到。"""

    class _Upper(WritePreprocessPluginInterface):
        def get_name(self) -> str:
            return "upper"

        def preprocess(self, text: str, ctx) -> str:
            return text.upper()

    pm = PluginManager()
    pm.register(_Upper())
    plugins = pm.get_all(PluginType.WRITE_PREPROCESS)
    assert len(plugins) == 1
    assert plugins[0].get_name() == "upper"


def test_deprecated_preprocess_alias_emits_warning():
    """导入废弃的 PreprocessPluginInterface 应发出 DeprecationWarning。"""
    import warnings

    with warnings.catch_warnings(record=True) as w:
        warnings.simplefilter("always")
        # 重新导入以触发警告
        import importlib

        import mcs.interfaces.preprocess_plugin as pp
        importlib.reload(pp)

        assert len(w) == 1
        assert issubclass(w[0].category, DeprecationWarning)
        assert "deprecated" in str(w[0].message).lower()


def test_write_preprocess_chain_is_sequential():
    """多个 WritePreprocessPlugin 串行执行，前一个输出是后一个输入。"""

    class _Prefix(WritePreprocessPluginInterface):
        def __init__(self, prefix: str, **kw):
            super().__init__(**kw)
            self._prefix = prefix

        def get_name(self) -> str:
            return f"prefix_{self._prefix}"

        def get_priority(self) -> int:
            return 0

        def preprocess(self, text: str, ctx) -> str:
            return f"{self._prefix}{text}"

    pm = PluginManager()
    pm.register(_Prefix(prefix="B:"))
    pm.register(_Prefix(prefix="A:", config={"priority": 10}))
    # 需要让 B 的优先级低于 A
    pm._plugins.clear()
    pm._by_type.clear()
    pm.register(_Prefix(prefix="A:", config={"priority": 10}))
    pm.register(_Prefix(prefix="B:"))

    plugins = pm.get_all(PluginType.WRITE_PREPROCESS)
    result = "hello"
    for p in plugins:
        result = p.preprocess(result, None)
    assert result == "B:A:hello"


def test_query_engine_has_no_read_chain_for_position():
    """QueryEngine 不再包含 _read_chain_for_position 方法。"""
    from mcs.core.query_engine import QueryEngine

    assert not hasattr(QueryEngine, "_read_chain_for_position")

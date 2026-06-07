"""插件链组合规则测试。"""

from __future__ import annotations

from typing import Any

import pytest

from mcs.core.errors import ConfigurationError
from mcs.core.graph import Node
from mcs.core.plugin_manager import PluginManager
from mcs.interfaces.arbitration_plugin import ArbitrationPluginInterface
from mcs.interfaces.entry_plugin import EntryPluginInterface
from mcs.interfaces.postprocess_plugin import PostprocessPluginInterface
from mcs.interfaces.query_preprocess_plugin import QueryPreprocessPluginInterface
from mcs.interfaces.write_preprocess_plugin import WritePreprocessPluginInterface
from mcs.core.plugin import PluginType

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


# === ArbitrationPlugin 单例 ===


class _Arb(ArbitrationPluginInterface):
    def arbitrate(self, accumulated, query, ctx):
        return accumulated


def test_registering_first_arbitration_plugin_succeeds():
    pm = PluginManager()

    class _Arb1(_Arb):
        def get_name(self) -> str:
            return "arb1"

    pm.register(_Arb1())


def test_registering_second_arbitration_plugin_raises():
    pm = PluginManager()

    class _Arb1(_Arb):
        def get_name(self) -> str:
            return "arb1"

    class _Arb2(_Arb):
        def get_name(self) -> str:
            return "arb2"

    pm.register(_Arb1())
    with pytest.raises(ConfigurationError):
        pm.register(_Arb2())


# === Postprocess 输出类型自由 ===


def test_postprocess_can_return_arbitrary_type():
    """Postprocess 插件可以返回任意类型——框架不做约束。"""

    class _ToInt(PostprocessPluginInterface):
        def get_name(self) -> str:
            return "to_int"

        def process(self, input, ctx):
            return len(input) if hasattr(input, "__len__") else 0

    p = _ToInt()
    assert p.process(["a", "b", "c"], None) == 3
    assert p.process("hello", None) == 5


# === Preprocess 插件类型 ===


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


def test_query_preprocess_plugin_type_registered_and_found():
    """QueryPreprocessPlugin 注册后可通过 PluginType.QUERY_PREPROCESS 查找到。"""

    class _Lower(QueryPreprocessPluginInterface):
        def get_name(self) -> str:
            return "lower"

        def preprocess(self, text: str, ctx) -> str:
            return text.lower()

    pm = PluginManager()
    pm.register(_Lower())
    plugins = pm.get_all(PluginType.QUERY_PREPROCESS)
    assert len(plugins) == 1
    assert plugins[0].get_name() == "lower"


def test_write_and_query_preprocess_are_separate_types():
    """WRITE_PREPROCESS 和 QUERY_PREPROCESS 是独立类型，互不干扰。"""

    class _Upper(WritePreprocessPluginInterface):
        def get_name(self) -> str:
            return "upper"

        def preprocess(self, text: str, ctx) -> str:
            return text.upper()

    class _Lower(QueryPreprocessPluginInterface):
        def get_name(self) -> str:
            return "lower"

        def preprocess(self, text: str, ctx) -> str:
            return text.lower()

    pm = PluginManager()
    pm.register(_Upper())
    pm.register(_Lower())

    assert len(pm.get_all(PluginType.WRITE_PREPROCESS)) == 1
    assert len(pm.get_all(PluginType.QUERY_PREPROCESS)) == 1
    assert pm.get_all(PluginType.WRITE_PREPROCESS)[0].get_name() == "upper"
    assert pm.get_all(PluginType.QUERY_PREPROCESS)[0].get_name() == "lower"


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


def test_preprocess_and_postprocess_are_separate_types():
    """Preprocess 和 Postprocess 是独立类型，互不干扰。"""

    class _Upper(WritePreprocessPluginInterface):
        def get_name(self) -> str:
            return "upper"

        def preprocess(self, text: str, ctx) -> str:
            return text.upper()

    class _Len(PostprocessPluginInterface):
        def get_name(self) -> str:
            return "len"

        def process(self, input, ctx):
            return len(input) if hasattr(input, "__len__") else 0

    pm = PluginManager()
    pm.register(_Upper())
    pm.register(_Len())

    assert len(pm.get_all(PluginType.WRITE_PREPROCESS)) == 1
    assert len(pm.get_all(PluginType.POSTPROCESS)) == 1
    assert pm.get_all(PluginType.WRITE_PREPROCESS)[0].get_name() == "upper"
    assert pm.get_all(PluginType.POSTPROCESS)[0].get_name() == "len"


def test_postprocess_no_position_attribute():
    """PostprocessPluginInterface 不再有 position 属性。"""
    assert not hasattr(PostprocessPluginInterface, "position")


def test_query_engine_has_no_read_chain_for_position():
    """QueryEngine 不再包含 _read_chain_for_position 方法。"""
    from mcs.core.query_engine import QueryEngine

    assert not hasattr(QueryEngine, "_read_chain_for_position")

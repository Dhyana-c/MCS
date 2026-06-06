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

"""插件链组合规则测试。"""

from __future__ import annotations

from typing import Any, ClassVar

import pytest

from mcs.core.errors import ConfigurationError
from mcs.core.graph import Node
from mcs.core.plugin_manager import PluginManager
from mcs.interfaces.arbitration_plugin import ArbitrationPluginInterface
from mcs.interfaces.entry_plugin import EntryPluginInterface
from mcs.interfaces.postprocess_plugin import PostprocessPluginInterface
from mcs.plugins.base import Plugin

# === EntryPlugin 优先级排序 ===


class _Entry(Plugin, EntryPluginInterface):
    interfaces: ClassVar[list[type]] = [EntryPluginInterface]

    def initialize(self, ctx: Any) -> None:
        return None

    def shutdown(self) -> None:
        return None

    def locate(self, query: str, ctx: Any) -> list[Node]:
        return []


class _High(_Entry):
    name = "high"
    priority = 100


class _Mid(_Entry):
    name = "mid"
    priority = 50


class _Low(_Entry):
    name = "low"
    priority = 0


def test_entry_plugins_returned_in_priority_descending():
    pm = PluginManager()
    pm.register(_Low())
    pm.register(_High())
    pm.register(_Mid())
    plugins = pm.get_all(EntryPluginInterface)
    assert [p.name for p in plugins] == ["high", "mid", "low"]


def test_entry_plugin_default_priority_is_zero():
    class _Default(_Entry):
        name = "default"

    p = _Default()
    assert p.priority == 0
    assert p.exclusive is False


def test_entry_plugin_exclusive_attribute():
    class _Excl(_Entry):
        name = "ex"
        priority = 50
        exclusive = True

    p = _Excl()
    assert p.exclusive is True


# === ArbitrationPlugin 单例 ===


class _Arb(Plugin, ArbitrationPluginInterface):
    interfaces: ClassVar[list[type]] = [ArbitrationPluginInterface]

    def initialize(self, ctx):
        return None

    def shutdown(self):
        return None

    def arbitrate(self, accumulated, query, ctx):
        return accumulated


def test_registering_first_arbitration_plugin_succeeds():
    pm = PluginManager()
    pm.register(type("_Arb1", (_Arb,), {"name": "arb1"})())


def test_registering_second_arbitration_plugin_raises():
    pm = PluginManager()
    pm.register(type("_Arb1", (_Arb,), {"name": "arb1"})())
    with pytest.raises(ConfigurationError):
        pm.register(type("_Arb2", (_Arb,), {"name": "arb2"})())


# === Postprocess 输出类型自由 ===


def test_postprocess_can_return_arbitrary_type():
    """Postprocess 插件可以返回任意类型——框架不做约束。"""

    class _ToInt(Plugin, PostprocessPluginInterface):
        name = "to_int"
        interfaces = [PostprocessPluginInterface]

        def initialize(self, ctx):
            pass

        def shutdown(self):
            pass

        def process(self, input, ctx):
            return len(input) if hasattr(input, "__len__") else 0

    p = _ToInt()
    assert p.process(["a", "b", "c"], None) == 3
    assert p.process("hello", None) == 5

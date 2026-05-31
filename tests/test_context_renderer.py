"""ContextRenderer 测试：目的驱动的渲染 + extension 贡献。"""

from __future__ import annotations

from typing import Any, ClassVar

import pytest

from mcs.core.context_renderer import ContextRenderer
from mcs.core.graph import Node
from mcs.core.plugin_manager import PluginManager
from mcs.interfaces.node_extension import NodeExtensionInterface
from mcs.plugins.base import Plugin


class FakeSourceExt(Plugin, NodeExtensionInterface):
    """最小的 NodeExt，仅在 purpose='synthesize' 时贡献内容。"""

    name: ClassVar[str] = "fake_source"
    interfaces: ClassVar[list[type]] = [NodeExtensionInterface]

    def initialize(self, ctx: Any) -> None:
        return None

    def shutdown(self) -> None:
        return None

    def schema(self) -> dict:
        return {"src": "str"}

    def default(self) -> dict:
        return {"src": ""}

    def serialize(self, data: Any) -> dict:
        return data or {}

    def deserialize(self, data: dict) -> dict:
        return data

    def render(self, node: Node, purpose: str) -> str | None:
        if purpose != "synthesize":
            return None
        slot = (node.extensions or {}).get(self.name, {})
        src = slot.get("src") if isinstance(slot, dict) else None
        if not src:
            return None
        return f"src={src}"


def _make_pm_with(*plugins) -> PluginManager:
    pm = PluginManager()
    for p in plugins:
        pm.register(p)
    return pm


def test_empty_input_returns_placeholder():
    r = ContextRenderer()
    assert "无" in r.render([], "synthesize")
    assert "无" in r.render(None, "synthesize")


def test_focus_node_uses_full_content_by_default():
    n = Node(id="a", name="A", content="long content here")
    r = ContextRenderer()
    out = r.render([n], "synthesize")
    assert "A" in out
    assert "long content here" in out
    assert "(id=a)" in out


def test_decide_directions_uses_summary_for_neighbors():
    focus = Node(id="f", name="F", content="focus content")
    neighbor = Node(
        id="nb",
        name="NB",
        content="neighbor content full",
        extensions={"summary": {"text": "neighbor short"}},
    )
    r = ContextRenderer()
    out = r.render([focus, neighbor], "decide_directions")
    assert "focus content" in out  # focus 使用完整内容
    assert "neighbor short" in out  # neighbor 降级为摘要
    assert "neighbor content full" not in out


def test_arbitrate_uses_summary_for_all_nodes():
    a = Node(
        id="1",
        name="N1",
        content="long A",
        extensions={"summary": {"text": "short A"}},
    )
    b = Node(
        id="2",
        name="N2",
        content="long B",
        extensions={"summary": {"text": "short B"}},
    )
    r = ContextRenderer()
    out = r.render([a, b], "arbitrate")
    assert "short A" in out and "short B" in out
    assert "long A" not in out and "long B" not in out


def test_extension_contributes_only_for_synthesize_purpose():
    pm = _make_pm_with(FakeSourceExt())
    r = ContextRenderer(pm)
    n = Node(
        id="n",
        name="N",
        content="content",
        extensions={"fake_source": {"src": "doc-42"}},
    )
    syn_out = r.render([n], "synthesize")
    dec_out = r.render([n], "decide_directions")
    assert "src=doc-42" in syn_out
    assert "src=doc-42" not in dec_out


def test_get_summary_fallback_without_extension():
    n = Node(id="x", name="X", content="hello world")
    assert ContextRenderer.get_summary(n) == "hello world"


def test_get_summary_long_content_truncated():
    long = "x" * 500
    n = Node(id="x", name="X", content=long)
    assert ContextRenderer.get_summary(n) == "x" * 200


def test_get_summary_prefers_extension():
    n = Node(
        id="x",
        name="X",
        content="long",
        extensions={"summary": {"text": "short"}},
    )
    assert ContextRenderer.get_summary(n) == "short"


# 减少 pytest 自动发现时 ruff 对 "unused import" 的警告。
_ = pytest

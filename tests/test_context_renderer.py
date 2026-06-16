"""ContextRenderer 测试：目的驱动的渲染 + extension 贡献。"""

from __future__ import annotations

from typing import Any

import pytest

from mcs.core.context_renderer import ContextRenderer
from mcs.core.plugin_manager import PluginManager
from mcs.entities.graph import Node
from mcs.interfaces.node_extension import NodeExtensionInterface


class FakeSourceExt(NodeExtensionInterface):
    """最小的 NodeExt，仅在 purpose='synthesize' 时贡献内容。"""

    def get_name(self) -> str:
        return "fake_source"

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
        slot = (node.extensions or {}).get("fake_source", {})
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


# ─── Task 1.3: 口径统一单测（name==content 去重、估算 == 渲染）───────────────────


def test_render_node_full_deduplicates_name_equals_content():
    """name==content 时正文去重——在实际渲染口径（render_node_full）生效。"""
    n = Node(id="a", name="Fantasy Football", content="Fantasy Football")
    out = ContextRenderer.render_node_full(n, purpose="decide_hub", is_focus=True)
    # name 只在头行出现一次，正文被省略
    assert out == "- Fantasy Football (id=a)"
    assert out.count("Fantasy Football") == 1


def test_render_node_full_writes_both_when_different():
    """name!=content 时正文照写（含义独立成行）。"""
    n = Node(id="a", name="AI", content="Artificial Intelligence")
    out = ContextRenderer.render_node_full(n, purpose="decide_hub", is_focus=True)
    assert out == "- AI (id=a)\n  Artificial Intelligence"


def test_render_node_full_empty_content():
    """content 为空时只有头行。"""
    n = Node(id="a", name="Topic", content="")
    out = ContextRenderer.render_node_full(n, purpose="decide_hub", is_focus=True)
    assert out == "- Topic (id=a)"

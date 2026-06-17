"""测试用边扩展插件（import-path 可达）。

供 config-file-loading 集成测试引用 ``"tests._support.edge_ext:SampleEdgeExt"``
验证 from_file → Phase1Builder.build() 的 import-path 解析。
"""

from __future__ import annotations

from typing import Any

from mcs.core.plugin import PluginType
from mcs.entities.graph import Edge
from mcs.interfaces.edge_extension import EdgeExtensionInterface


class SampleEdgeExt(EdgeExtensionInterface):
    """``edge.extensions["sample"] = {"weight": int}``；select_facts 渲染权重。"""

    def get_name(self) -> str:
        return "sample"

    def get_type(self) -> PluginType:
        return PluginType.EDGE_EXTENSION

    def schema(self) -> dict:
        return {"weight": "int"}

    def default(self) -> dict:
        return {"weight": 0}

    def serialize(self, data: Any) -> dict:
        d = data or {}
        return {"weight": d.get("weight", 0)}

    def deserialize(self, data: dict) -> dict:
        d = data or {}
        return {"weight": d.get("weight", 0)}

    def render(self, edge: Edge, purpose: str) -> str | None:
        if purpose != "select_facts":
            return None
        d = (edge.extensions or {}).get("sample", {})
        w = d.get("weight", 0) if isinstance(d, dict) else 0
        return f"权重={w}" if w else None

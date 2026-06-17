"""MCS 作为 MCP（Model Context Protocol）server 暴露的薄适配层。

把 MCS 的 ``ingest`` / ``query`` 包成 MCP 工具，经 stdio 传输服务客户端（如 Claude Desktop）。
``mcp`` 与 ``PyYAML`` 为可选依赖（``pip install mcs[mcp]``）；核心库不强依赖它们。

启动：``mcs-mcp``（console 入口）或 ``python -m mcs.mcp``（见 ``__main__.py``）。
"""

from __future__ import annotations


def __getattr__(name: str):  # pragma: no cover - 仅按需暴露
    if name == "main":
        from mcs.mcp.server import main

        return main
    raise AttributeError(f"module 'mcs.mcp' has no attribute {name!r}")

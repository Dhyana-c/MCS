"""mcp-server 测试（§1.2 / §2.3 / §3.4 / §4.3 / §5.2 / §6.4 / §8.1 / §8.2）。

工具处理函数（``MCPServer.run_query``/``run_ingest`` 与纯函数）不依赖 MCP 传输，单测在
处理函数层面进行；``build_fastmcp`` + ``call_tool`` 做传输层 smoke（内存、无需真实 stdio）。
"""

from __future__ import annotations

import threading
import time
from pathlib import Path
from typing import Any

import pytest

from mcs.entities.graph import Node, Subgraph
from mcs.mcp.server import (
    MCPServer,
    _format_ingest_status,
    _render_query_result,
    build_fastmcp,
    main,
)

MOCK_CONFIG = """
write_llm: mock_llm
read_llm: mock_llm
shared_plugins:
  - tests.conftest:MockLLM
  - summary
write_plugins: []
read_plugins:
  - alias_index
  - alias_entry
  - hub_fallback
  - priority_trim
token_budget: 8000
"""


def _write_config(tmp_path: Path, text: str = MOCK_CONFIG) -> str:
    p = tmp_path / "mcs.yaml"
    p.write_text(text, encoding="utf-8")
    return str(p)


class _FakeMCS:
    """替身 MCS：记录调用线程、检测并发重入（验证串行化）、可控抛异常。"""

    def __init__(
        self,
        query_result: Any = None,
        query_exc: Exception | None = None,
        ingest_exc: Exception | None = None,
    ) -> None:
        self._query_result = query_result
        self._query_exc = query_exc
        self._ingest_exc = ingest_exc
        self.read_manager = None
        self.call_thread_ids: list[tuple[str, int]] = []
        self._in_call = False

    def _enter(self, kind: str) -> None:
        self.call_thread_ids.append((kind, threading.get_ident()))
        if self._in_call:
            raise RuntimeError("REENTRANT: concurrent MCS access detected (serialization broken)")
        self._in_call = True

    def _exit(self) -> None:
        self._in_call = False

    def query(self, query: str) -> Any:
        self._enter("query")
        try:
            if self._query_exc is not None:
                raise self._query_exc
            time.sleep(0.02)  # 拉宽窗口：若无串行化，并发必在此重叠
            return self._query_result
        finally:
            self._exit()

    def ingest(self, text: str) -> Any:
        self._enter("ingest")
        try:
            if self._ingest_exc is not None:
                raise self._ingest_exc
            time.sleep(0.02)
            return _FakeWriteContext()
        finally:
            self._exit()

    def shutdown(self) -> None:
        pass


class _FakeWriteContext:
    def __init__(self) -> None:
        self.changed = [object(), object()]
        self.concepts = [object()]
        self.persisted = True


@pytest.fixture
def server(tmp_path: Path) -> MCPServer:
    """从 mock 配置 build 出真实 MCPServer（单 worker）；测试中可替换 _mcs。"""
    s = MCPServer(_write_config(tmp_path))
    yield s
    s.shutdown()


# ── §1.2 入口：缺配置 / 文件不存在 ──────────────────────────────────────────


def test_main_missing_config(monkeypatch, tmp_path: Path):
    monkeypatch.delenv("MCS_CONFIG", raising=False)
    assert main([]) == 2


def test_main_config_file_not_found(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("MCS_CONFIG", str(tmp_path / "nope.yaml"))
    assert main([]) == 2


def test_main_resolves_config_from_env(monkeypatch, tmp_path: Path):
    # 配置存在但 mcp 缺失 → 应走到 mcp 缺失分支（证明 MCS_CONFIG 被解析、文件被找到）
    path = _write_config(tmp_path)
    monkeypatch.setenv("MCS_CONFIG", path)

    import builtins
    import sys

    real_import = builtins.__import__

    def fake_import(name, *a, **k):
        if name == "mcp":
            raise ImportError("simulated: No module named 'mcp'")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    monkeypatch.delitem(sys.modules, "mcp", raising=False)
    assert main([]) == 1  # mcp 缺失分支


# ── §3.4 query 渲染 ─────────────────────────────────────────────────────────


def test_render_query_result_str_passthrough():
    assert _render_query_result("plain text", "property_graph", None) == "plain text"


def test_render_query_result_subgraph_renders_nodes():
    n = Node(id="a", name="深度学习", content="一种方法")
    out = _render_query_result(Subgraph(focus_id="a", nodes=[n]), "property_graph", None)
    assert "深度学习" in out
    assert "一种方法" in out


def test_render_query_result_other_falls_back_to_str():
    assert _render_query_result(12345, "property_graph", None) == "12345"


def test_run_query_renders_via_handler(server: MCPServer):
    server._mcs = _FakeMCS(
        query_result=Subgraph(focus_id="a", nodes=[Node(id="a", name="节点X", content="内容Y")])
    )
    out = server.run_query("q")
    assert "节点X" in out and "内容Y" in out


# ── §4.3 ingest 状态摘要 ────────────────────────────────────────────────────


def test_format_ingest_status_counts_and_no_edges():
    s = _format_ingest_status(_FakeWriteContext())
    assert "概念 1" in s
    assert "节点 +2" in s
    assert "persisted=yes" in s
    # MUST NOT 报边计数
    assert "边" not in s


def test_run_ingest_returns_status_string(server: MCPServer):
    server._mcs = _FakeMCS()
    out = server.run_ingest("text")
    assert isinstance(out, str)
    assert "已写入" in out


# ── §2.3 串行化 + 线程亲和 ──────────────────────────────────────────────────


def test_concurrent_calls_serial_and_same_thread(server: MCPServer):
    server._mcs = _FakeMCS(query_result=Subgraph(focus_id="a", nodes=[]))
    errors: list[BaseException] = []

    def caller() -> None:
        try:
            server.run_query("q")
        except BaseException as e:  # noqa: BLE001 - 收集所有错误（含 REENTRANT）
            errors.append(e)

    threads = [threading.Thread(target=caller) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    # 无 REENTRANT：并发被单 worker 串行化、不交错
    assert errors == []
    # 全部 MCS 访问发生在同一（worker）线程
    thread_ids = {tid for _, tid in server._mcs.call_thread_ids}  # type: ignore[union-attr]
    assert len(thread_ids) == 1
    assert server._worker_thread_id in thread_ids


def test_build_and_calls_use_same_thread(server: MCPServer):
    # build 与调用的线程一致（SQLite 线程亲和）
    server._mcs = _FakeMCS(query_result=Subgraph(focus_id="a", nodes=[]))
    server.run_query("q")
    assert server._mcs.call_thread_ids[0][1] == server._worker_thread_id  # type: ignore[union-attr]


# ── §5.2 错误隔离（经 FastMCP call_tool） ───────────────────────────────────


async def test_tool_exception_isolated_and_server_survives(server: MCPServer):
    # 第一次：内部抛异常 → 错误响应（不抛出）
    server._mcs = _FakeMCS(query_exc=RuntimeError("boom inside query"))
    mcp_server = build_fastmcp(server)

    result = await mcp_server.call_tool("query", {"query": "x"})
    text = _content_text(result)
    assert "error" in text
    assert "boom inside query" in text

    # 第二次：换回正常 → server 仍可服务下一次调用
    server._mcs = _FakeMCS(
        query_result=Subgraph(focus_id="a", nodes=[Node(id="a", name="恢复", content="ok")])
    )
    result2 = await mcp_server.call_tool("query", {"query": "x"})
    assert "恢复" in _content_text(result2)


# ── §6.4 mcp 缺失（build_fastmcp 层） ───────────────────────────────────────


def test_build_fastmcp_missing_mcp_reports_hint(monkeypatch):
    import builtins
    import sys

    real_import = builtins.__import__

    def fake_import(name, *a, **k):
        if name in ("mcp", "mcp.server.fastmcp"):
            raise ImportError("simulated: No module named 'mcp'")
        return real_import(name, *a, **k)

    monkeypatch.setattr(builtins, "__import__", fake_import)
    for mod in list(sys.modules):
        if mod == "mcp" or mod.startswith("mcp."):
            monkeypatch.delitem(sys.modules, mod, raising=False)

    server = object()  # build_fastmcp 在 import mcp 处即失败，不触碰 server
    with pytest.raises(ImportError, match=r"pip install mcs\[mcp\]"):
        build_fastmcp(server)  # type: ignore[arg-type]


# ── §8.1 集成：真实 build + handler 跑通 query/ingest ────────────────────────


def test_integration_handler_query_and_ingest(tmp_path: Path):
    s = MCPServer(_write_config(tmp_path))
    try:
        # handler 层面跑通（不依赖真实 MCP 传输）；mock LLM 默认返回空抽取
        q_out = s.run_query("任意查询")
        assert isinstance(q_out, str)
        i_out = s.run_ingest("一段用于集成测试的文本。")
        assert isinstance(i_out, str)
        assert "已写入" in i_out
    finally:
        s.shutdown()


# ── §8.2 传输层 smoke（内存 call_tool / list_tools） ─────────────────────────


async def test_smoke_list_tools_and_call(server: MCPServer):
    server._mcs = _FakeMCS(
        query_result=Subgraph(focus_id="a", nodes=[Node(id="a", name="N", content="C")])
    )
    mcp_server = build_fastmcp(server)

    tools = await mcp_server.list_tools()
    names = {t.name for t in tools}
    assert names == {"query", "ingest"}

    q = await mcp_server.call_tool("query", {"query": "x"})
    assert "N" in _content_text(q)

    i = await mcp_server.call_tool("ingest", {"text": "t"})
    assert "已写入" in _content_text(i)


# ── §8.3 核心库不因 MCP / PyYAML 缺失受影响（隔离子进程） ────────────────────


def test_core_imports_unaffected_by_missing_mcp_and_yaml():
    """mcp / pyyaml 缺失时，核心库（mcs / config / mcp 模块本身）导入 MUST 不受影响。

    MCP 为可选依赖：mcp 模块惰性导入 mcp、config 惰性导入 yaml。用隔离子进程阻断二者、
    强制重新导入验证（不污染本进程 sys.modules / 已加载类对象）。
    """
    import subprocess
    import sys
    import textwrap

    code = textwrap.dedent(
        """
        import builtins, sys
        _real = builtins.__import__
        def _block(name, *a, **k):
            if name == "mcp" or name.startswith("mcp.") or name == "yaml":
                raise ImportError("blocked: " + name)
            return _real(name, *a, **k)
        builtins.__import__ = _block
        for m in list(sys.modules):
            if m == "mcp" or m.startswith("mcp.") or m == "yaml":
                del sys.modules[m]
        import mcs                   # 核心库
        import mcs.entities.config   # config（yaml 惰性）
        import mcs.mcp.server        # MCP 模块（mcp 惰性）
        print("OK")
        """
    )
    r = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, env=None
    )
    assert r.returncode == 0, f"stdout={r.stdout!r}\nstderr={r.stderr!r}"
    assert "OK" in r.stdout


# ── 辅助 ────────────────────────────────────────────────────────────────────


def _content_text(result: Any) -> str:
    """从 FastMCP call_tool 的返回（ContentBlock 序列 / dict）提取纯文本。"""
    # FastMCP 的 call_tool 返回 (content_blocks, structured_dict) 元组
    if isinstance(result, tuple) and result:
        result = result[0]
    if isinstance(result, str):
        return result
    if isinstance(result, dict):
        for key in ("text", "result"):
            if key in result:
                return str(result[key])
        return str(result)
    parts: list[str] = []
    for block in result or []:
        text = getattr(block, "text", None)
        if text is not None:
            parts.append(str(text))
    return "".join(parts)

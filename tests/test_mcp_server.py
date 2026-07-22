"""mcp-server 测试（后端走 mcs_agent）。

工具处理函数（``MCPServer.run_query`` / ``run_ingest``）不依赖 MCP 传输，单测在处理函数
层面进行：
- **A 类**（mcs_mcp 层单测）：``MCPServer.from_agent`` 注入 ``_FakeAgent`` 测透传 / 异常隔离 /
  shutdown——此时 mcs_mcp 是被测对象、agent 是 collaborator 替身（非「mock 启动服务」）。
- **构造期早失败**：测 ``_llm_config_from_mcs`` 反推（无 LLM / provider 不支持 / 多歧义 / write_llm 消歧）。
- **B 类**（真实 agent loop）：``CallableAgentLLM``（项目内置注入适配器）+ 真实 ``MemoryAgent`` +
  最小 ``MemoryStore`` 测 implicit termination 链路（不 mock 掉 agent）。

``build_fastmcp`` + ``call_tool`` / ``list_tools`` 做传输层 smoke（内存、无需真实 stdio）。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from mcs.entities.config import MCSConfig
from mcs_mcp.server import (
    MCPServer,
    _McpConfigError,
    _llm_config_from_mcs,
    build_fastmcp,
    main,
)


# ── A 类 collaborator 替身 ─────────────────────────────────────────────────


class _FakeMemory:
    """MemoryStore 替身：``learn`` 返固定串、``shutdown`` 记录调用。"""

    def __init__(
        self,
        learn_reply: str = "已写入：1 个概念",
        learn_exc: Exception | None = None,
    ) -> None:
        self.learn_reply = learn_reply
        self.learn_exc = learn_exc
        self.shutdown_calls = 0
        self.learn_calls: list[str] = []
        self.learn_work_ids: list[str | None] = []  # A1：记录 work_id 透传

    def learn(self, text: str, work_id: str | None = None) -> str:
        self.learn_calls.append(text)
        self.learn_work_ids.append(work_id)
        if self.learn_exc is not None:
            raise self.learn_exc
        return self.learn_reply

    def shutdown(self) -> None:
        self.shutdown_calls += 1


class _FakeAgent:
    """MemoryAgent 替身：``chat`` 返固定串、``memory`` 是 _FakeMemory。"""

    def __init__(
        self,
        chat_reply: str = "agent reply",
        chat_exc: Exception | None = None,
        memory: _FakeMemory | None = None,
    ) -> None:
        self.chat_reply = chat_reply
        self.chat_exc = chat_exc
        self.memory = memory or _FakeMemory()
        self.chat_calls: list[str] = []

    def chat(self, query: str) -> str:
        self.chat_calls.append(query)
        if self.chat_exc is not None:
            raise self.chat_exc
        return self.chat_reply


def _write_minimal_config(tmp_path: Path) -> str:
    """含 deepseek_llm 的最小 yaml（供 main 解析；mcp 缺失分支不 build agent）。"""
    p = tmp_path / "mcs.yaml"
    p.write_text(
        "write_llm: deepseek_llm\n"
        "plugin_configs:\n"
        "  sqlite_storage:\n"
        "    path: ':memory:'\n"
        "  deepseek_llm:\n"
        "    api_key: dummy\n"
        "    model: deepseek-chat\n",
        encoding="utf-8",
    )
    return str(p)


# ── §1.2 入口：缺配置 / 文件不存在 ──────────────────────────────────────────


def test_main_missing_config(monkeypatch, tmp_path: Path):
    monkeypatch.delenv("MCS_CONFIG", raising=False)
    assert main([]) == 2


def test_main_config_file_not_found(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("MCS_CONFIG", str(tmp_path / "nope.yaml"))
    assert main([]) == 2


def test_main_resolves_config_from_env(monkeypatch, tmp_path: Path):
    # 配置存在但 mcp 缺失 → 走 mcp 缺失分支（证明 MCS_CONFIG 被解析、文件被找到）
    path = _write_minimal_config(tmp_path)
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


# ── A 类：query/ingest 委托 agent.chat / agent.memory.learn + 异常隔离 ──────


def test_run_query_delegates_to_agent_chat():
    agent = _FakeAgent(chat_reply="hello world")
    server = MCPServer.from_agent(agent)
    out = server.run_query("any query")
    assert out == "hello world"  # 原样透传、不包装
    assert agent.chat_calls == ["any query"]


def test_run_ingest_delegates_to_memory_learn():
    mem = _FakeMemory(learn_reply="已写入：3 个概念")
    agent = _FakeAgent(memory=mem)
    server = MCPServer.from_agent(agent)
    out = server.run_ingest("some text")
    assert out == "已写入：3 个概念"
    assert mem.learn_calls == ["some text"]


def test_run_ingest_passes_work_id_to_learn():
    """A1：run_ingest(text, work_id) 透传到 memory.learn（触发 ③b 作品事件抽取）。"""
    mem = _FakeMemory()
    agent = _FakeAgent(memory=mem)
    server = MCPServer.from_agent(agent)
    server.run_ingest("作品文本", work_id="三国演义")
    assert mem.learn_calls == ["作品文本"]
    assert mem.learn_work_ids == ["三国演义"]


def test_run_query_does_not_wrap_agent_reply():
    # agent 答复含特殊内容也原样透传（不截断/再渲染；含 [id:] 与 forced 字样也照传）
    reply = "答复含 [id:abc] 与「达到最大轮次」字样"
    agent = _FakeAgent(chat_reply=reply)
    server = MCPServer.from_agent(agent)
    assert server.run_query("q") == reply


async def test_tool_exception_isolated_and_server_survives():
    # 第一次：agent.chat 抛异常 → [error] 文本（不抛出）
    agent = _FakeAgent(chat_exc=RuntimeError("boom inside chat"))
    server = MCPServer.from_agent(agent)
    mcp_server = build_fastmcp(server)

    result = await mcp_server.call_tool("query", {"query": "x"})
    text = _content_text(result)
    assert "error" in text
    assert "boom inside chat" in text

    # 第二次：换正常 agent → server 仍可服务下一次调用
    agent2 = _FakeAgent(chat_reply="recovered")
    server2 = MCPServer.from_agent(agent2)
    mcp_server2 = build_fastmcp(server2)
    result2 = await mcp_server2.call_tool("query", {"query": "x"})
    assert "recovered" in _content_text(result2)


async def test_ingest_exception_isolated():
    mem = _FakeMemory(learn_exc=RuntimeError("ingest boom"))
    agent = _FakeAgent(memory=mem)
    server = MCPServer.from_agent(agent)
    mcp_server = build_fastmcp(server)
    result = await mcp_server.call_tool("ingest", {"text": "t"})
    text = _content_text(result)
    assert "error" in text
    assert "ingest boom" in text


def test_shutdown_calls_memory_shutdown():
    mem = _FakeMemory()
    agent = _FakeAgent(memory=mem)
    server = MCPServer.from_agent(agent)
    server.shutdown()
    # agent.memory.shutdown（非 agent.shutdown——MemoryAgent 无此方法）
    assert mem.shutdown_calls == 1


# ── 构造期早失败（_llm_config_from_mcs 反推） ─────────────────────────────


def _cfg(plugin_configs: dict, write_llm: str = "", read_llm: str = "") -> MCSConfig:
    return MCSConfig(
        plugin_configs=dict(plugin_configs), write_llm=write_llm, read_llm=read_llm
    )


def test_no_llm_plugin_early_fail():
    with pytest.raises(_McpConfigError, match="未配 agent 可用"):
        _llm_config_from_mcs(_cfg({"sqlite_storage": {"path": "x"}}))


def test_unsupported_provider_early_fail():
    # glm_llm provider 不在 AGENT_LLM_REGISTRY → 过滤后候选为空 → 同"无 agent 可用 LLM"
    with pytest.raises(_McpConfigError, match="未配 agent 可用"):
        _llm_config_from_mcs(_cfg({"glm_llm": {"model": "glm-4"}}, write_llm="glm_llm"))


def test_multiple_llm_ambiguous_early_fail():
    cfg = _cfg(
        {"deepseek_llm": {"model": "d"}, "claude_llm": {"auth_token": "t", "model": "c"}},
        write_llm="glm_llm",  # write_llm 不在候选 → 无法消歧
    )
    with pytest.raises(_McpConfigError, match="多个 agent 可用"):
        _llm_config_from_mcs(cfg)


def test_disambiguate_by_write_llm():
    cfg = _cfg(
        {"deepseek_llm": {"model": "d"}, "claude_llm": {"auth_token": "t", "model": "c"}},
        write_llm="deepseek_llm",  # write_llm 在候选 → 取 deepseek
    )
    kwargs = _llm_config_from_mcs(cfg)
    assert kwargs["llm_provider"] == "deepseek"
    assert kwargs["llm_model"] == "d"


def test_single_candidate_success_deepseek():
    cfg = _cfg(
        {"deepseek_llm": {"model": "deepseek-chat", "api_key": "k"}},
        write_llm="deepseek_llm",
    )
    kwargs = _llm_config_from_mcs(cfg)
    assert kwargs["llm_provider"] == "deepseek"
    assert kwargs["llm_model"] == "deepseek-chat"
    assert kwargs["llm_api_key"] == "k"
    assert kwargs["llm_auth_token"] is None
    assert kwargs["mcs_config"] is cfg  # 逃逸口透传


def test_claude_auth_token_preferred():
    cfg = _cfg(
        {"claude_llm": {"auth_token": "tok", "api_key": "fallback", "model": "claude-3"}},
        write_llm="claude_llm",
    )
    kwargs = _llm_config_from_mcs(cfg)
    assert kwargs["llm_provider"] == "claude"
    assert kwargs["llm_auth_token"] == "tok"
    assert kwargs["llm_api_key"] == ""  # 有 auth_token 则 api_key 空


def test_single_candidate_warns_on_write_llm_mismatch(caplog):
    # write_llm 指向不支持的 provider（glm_llm），唯一支持候选 deepseek_llm → 取 deepseek + warn
    cfg = _cfg({"deepseek_llm": {"model": "d"}}, write_llm="glm_llm")
    with caplog.at_level("WARNING"):
        kwargs = _llm_config_from_mcs(cfg)
    assert kwargs["llm_provider"] == "deepseek"
    assert any("write_llm" in r.message for r in caplog.records)


def test_single_candidate_no_warn_when_write_llm_empty(caplog):
    """write_llm 未设（默认 ''）+ 单候选 → 不误报 warning（合法配置；#1 修复防回归）。"""
    cfg = MCSConfig(
        plugin_configs={"deepseek_llm": {"model": "d", "api_key": "k"}},
        write_llm="",
        read_llm="",
    )
    with caplog.at_level("WARNING"):
        kwargs = _llm_config_from_mcs(cfg)
    assert kwargs["llm_provider"] == "deepseek"
    assert not any("write_llm" in r.message for r in caplog.records)


# ── B 类：真实 MemoryAgent + CallableAgentLLM 链路（不 mock agent loop） ────


class _MinimalFakeStore:
    def get_graph_meta(self, key: str) -> str:
        return ""


class _MinimalFakeMCS:
    """仅支持 graph_summary 调用链的最小 MCS（implicit termination 不调其他原语）。"""

    def __init__(self) -> None:
        self.store = _MinimalFakeStore()

    def shutdown(self) -> None:
        pass


def test_query_implicit_termination_via_real_loop():
    """B 类：脚本化 LLM 首轮无 tool_calls → 真实 MemoryAgent 直接答复 → run_query 透传。

    验证 mcs_mcp 走真实 agent loop（``CallableAgentLLM`` 注入、非 mock 掉 agent）。
    memory 用最小 fake（implicit termination 不调 search/learn 等原语，仅需 graph_summary）。
    """
    from mcs_agent.loop import MemoryAgent
    from mcs_agent.memory import MemoryStore

    def llm_call(messages, tools):
        return {"content": "real-agent final answer", "tool_calls": []}

    memory = MemoryStore(build_fn=lambda: _MinimalFakeMCS())
    try:
        agent = MemoryAgent(memory, llm_call, max_turns=4)
        server = MCPServer.from_agent(agent)
        out = server.run_query("anything")
        assert out == "real-agent final answer"
    finally:
        memory.shutdown()


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


# ── §8.2 传输层 smoke（内存 list_tools） ────────────────────────────────────


async def test_smoke_list_tools():
    agent = _FakeAgent(chat_reply="ok")
    server = MCPServer.from_agent(agent)
    mcp_server = build_fastmcp(server)
    tools = await mcp_server.list_tools()
    names = {t.name for t in tools}
    assert names == {"query", "ingest"}


# ── import 洁净：不拉 fastapi（防误 import mcs_agent.app） ──────────────────


def test_core_imports_unaffected_by_missing_mcp_and_yaml():
    """mcp / pyyaml 缺失时核心库导入不受影响；``import mcs_mcp.server`` MUST NOT 间接拉
    fastapi / pydantic / uvicorn（防误 ``import mcs_agent.app``）。

    隔离子进程阻断 mcp / yaml、强制重新导入验证（不污染本进程 sys.modules）。
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
        import mcs
        import mcs.entities.config
        import mcs_mcp.server
        leaked = [m for m in ("fastapi", "pydantic", "uvicorn") if m in sys.modules]
        assert not leaked, f"unexpected HTTP stack imported: {leaked}"
        print("OK")
        """
    )
    r = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True, env=None
    )
    assert r.returncode == 0, f"stdout={r.stdout!r}\nstderr={r.stderr!r}"
    assert "OK" in r.stdout


# ── 核心修复针对性测试（mcp-via-agent D6 / D7） ─────────────────────────────


def test_memory_store_init_failure_shuts_down_executor(monkeypatch):
    """``MemoryStore.__init__`` 的 build_fn 抛 → 异常传播 + ``executor.shutdown(wait=False)`` 被调。

    防构造失败时 worker + executor 无引用靠 GC 泄漏（mcp-via-agent D6）。build_fn 在 worker
    内抛是构造失败最高频路径（坏 yaml / 坏 sqlite path）。
    """
    from concurrent.futures import ThreadPoolExecutor

    from mcs_agent.memory import MemoryStore

    shutdown_calls: list[dict] = []
    orig_shutdown = ThreadPoolExecutor.shutdown

    def tracking_shutdown(self, *args, **kwargs):
        shutdown_calls.append({"args": args, "kwargs": kwargs})
        return orig_shutdown(self, *args, **kwargs)

    monkeypatch.setattr(ThreadPoolExecutor, "shutdown", tracking_shutdown)

    def boom():
        raise RuntimeError("build failed")

    with pytest.raises(RuntimeError, match="build failed"):
        MemoryStore(boom)
    # 兜底调了 executor.shutdown(wait=False)——worker + executor 被释放
    assert any(c["kwargs"].get("wait") is False for c in shutdown_calls)


def test_builder_build_step3_failure_shuts_down_memory(monkeypatch, tmp_path):
    """``AgentBuilder.build`` 步骤 3（构造 backend）抛 → ``memory.shutdown()`` 被调（防泄漏，D6）。

    monkeypatch ``AGENT_LLM_REGISTRY`` 注入构造即抛的 backend 类，断言异常传播且已建的
    MemoryStore 被 shutdown（不靠 GC）。
    """
    from mcs_agent import builder as builder_mod
    from mcs_agent.builder import create_agent

    class _BoomBackend:
        def __init__(self, *a, **k):
            raise RuntimeError("backend construction failed")

    monkeypatch.setitem(builder_mod.AGENT_LLM_REGISTRY, "deepseek", _BoomBackend)

    shutdown_calls = [0]
    orig = builder_mod.MemoryStore.shutdown

    def tracking_shutdown(self):
        shutdown_calls[0] += 1
        return orig(self)

    monkeypatch.setattr(builder_mod.MemoryStore, "shutdown", tracking_shutdown)

    with pytest.raises(RuntimeError, match="backend construction failed"):
        create_agent(
            db_path=str(tmp_path / "t.db"),
            llm_provider="deepseek",
            llm_model="m",
            llm_api_key="k",
        )
    assert shutdown_calls[0] == 1  # 步骤 3 失败 → memory.shutdown 被调一次


def test_openai_adapter_get_client_lock_prevents_double_init(monkeypatch):
    """并发 ``_get_client`` → OpenAI client 只构造一次（D7 锁，防 double-init 连接池泄漏）。

    8 线程经 Barrier 同时调 ``_get_client``，构造内 sleep 拉宽窗口——无锁必 double-init；
    加锁后 ``construct_count == 1`` 且全线程拿同一实例。
    """
    import sys
    import threading
    import time
    import types
    from unittest.mock import MagicMock

    from mcs_agent.llms.openai import OpenAIAgentLLM

    construct_count = [0]
    count_lock = threading.Lock()

    class _FakeOpenAI:
        def __init__(self, **kwargs):
            with count_lock:
                construct_count[0] += 1
            time.sleep(0.05)  # 拉宽窗口：无锁则并发 double-init
            self.chat = MagicMock()

    fake_mod = types.ModuleType("openai")
    fake_mod.OpenAI = _FakeOpenAI
    monkeypatch.setitem(sys.modules, "openai", fake_mod)

    backend = OpenAIAgentLLM("model", "key", base_url="http://x")
    barrier = threading.Barrier(8)
    results: list[Any] = []

    def get():
        barrier.wait()
        results.append(backend._get_client())

    threads = [threading.Thread(target=get) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert construct_count[0] == 1  # 锁保护：只构造一次
    assert all(r is results[0] for r in results)  # 全同一实例


# ── §1.2 main 的 _McpConfigError 捕获分支 ────────────────────────────────────


def test_main_no_llm_plugin_returns_1(monkeypatch, tmp_path):
    """无 ``*_llm`` 的 yaml → ``_llm_config_from_mcs`` 抛 ``_McpConfigError`` → main 捕获返 1。"""
    p = tmp_path / "no_llm.yaml"
    p.write_text(
        "plugin_configs:\n  sqlite_storage:\n    path: ':memory:'\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("MCS_CONFIG", str(p))
    assert main([]) == 1


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

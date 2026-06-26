"""工具注册表测试：ToolSpec / BUILTIN_TOOLS / ToolsetConfig / build_toolset + _dispatch 包装层。

mock LLM（脚本化 callable）+ fake memory，不依赖真实 API / 真实 MCS。
"""

from __future__ import annotations

from mcs_agent.loop import MemoryAgent
from mcs_agent.tools import BUILTIN_TOOLS, MEMORY_TOOLS, ToolSpec, ToolsetConfig, build_toolset


# === ToolSpec / BUILTIN_TOOLS / MEMORY_TOOLS 别名 ===


def test_builtin_tools_has_5():
    assert set(BUILTIN_TOOLS) == {"learn", "search", "associate", "reason", "recall"}
    for spec in BUILTIN_TOOLS.values():
        assert isinstance(spec, ToolSpec)
        assert spec.schema["type"] == "function"


def test_memory_tools_alias_is_5_schemas():
    """MEMORY_TOOLS 废弃别名 = 全 5 内置 schemas（保 import 不断裂）。"""
    assert len(MEMORY_TOOLS) == 5
    assert [s["function"]["name"] for s in MEMORY_TOOLS] == [
        "learn",
        "search",
        "associate",
        "reason",
        "recall",
    ]


# === build_toolset ===


def test_build_toolset_default_all_5():
    schemas, dispatch = build_toolset(BUILTIN_TOOLS, None)
    names = {s["function"]["name"] for s in schemas}
    assert names == {"learn", "search", "associate", "reason", "recall"}
    assert set(dispatch) == names
    for _, params in dispatch.values():
        assert params == {}  # 默认无 params


def test_build_toolset_enabled_subset():
    schemas, dispatch = build_toolset(BUILTIN_TOOLS, ToolsetConfig(enabled=["search", "learn"]))
    names = {s["function"]["name"] for s in schemas}
    assert names == {"search", "learn"}
    assert set(dispatch) == names


def test_build_toolset_unknown_enabled_ignored():
    """enabled 含未知名：跳过（不暴露 schema、dispatch 缺省）。"""
    schemas, dispatch = build_toolset(BUILTIN_TOOLS, ToolsetConfig(enabled=["search", "ghost"]))
    assert {s["function"]["name"] for s in schemas} == {"search"}
    assert "ghost" not in dispatch


def test_build_toolset_params_by_tool_name():
    """params key = 工具名（非原语名 reason → 非 find_path）。"""
    _, dispatch = build_toolset(BUILTIN_TOOLS, ToolsetConfig(params={"reason": {"max_hops": 8}}))
    _, params = dispatch["reason"]
    assert params == {"max_hops": 8}
    # find_path（原语名）作 key 应不命中
    _, dispatch2 = build_toolset(BUILTIN_TOOLS, ToolsetConfig(params={"find_path": {"max_hops": 8}}))
    assert dispatch2["reason"][1] == {}  # find_path key 未命中 reason


# === _dispatch 包装层（经 MemoryAgent + fake memory） ===


class _Memory:
    def __init__(self) -> None:
        self.find_path_calls: list[tuple[str, str, int]] = []

    def find_path(self, s: str, t: str, max_hops: int = 6) -> str:
        self.find_path_calls.append((s, t, max_hops))
        return f"path {s}->{t} hops={max_hops}"

    def learn(self, t: str) -> str:
        return "ok"

    def search(self, q: str, mode: str = "keyword") -> str:
        return "ok"

    def associate(self, s: str, mode: str = "mcs") -> str:
        return "ok"

    def recall(self, limit: int = 5) -> str:
        return "ok"


def _tc(call_id: str, name: str, args: str) -> dict:
    return {"id": call_id, "type": "function", "function": {"name": name, "arguments": args}}


def _assistant(content: str | None = None, tool_calls: list[dict] | None = None) -> dict:
    m: dict = {"role": "assistant", "content": content}
    if tool_calls:
        m["tool_calls"] = tool_calls
    return m


def test_dispatch_params_override_default():
    """ToolsetConfig.params.max_hops=8 覆盖 handler 缺省 6（LLM 不传时）。"""
    mem = _Memory()
    replies = iter(
        [_assistant(tool_calls=[_tc("1", "reason", '{"source_id":"a","target_id":"b"}')]), _assistant(content="done")]
    )
    agent = MemoryAgent(mem, lambda m, t: next(replies), tools=ToolsetConfig(params={"reason": {"max_hops": 8}}))
    assert agent.chat("x") == "done"
    assert mem.find_path_calls == [("a", "b", 8)]


def test_dispatch_params_override_llm_same_name():
    """params 与 LLM 入参同名时以 params 为准。"""
    mem = _Memory()
    # LLM 传 max_hops=2，params 给 max_hops=8 → 合并后 8
    replies = iter(
        [_assistant(tool_calls=[_tc("1", "reason", '{"source_id":"a","target_id":"b","max_hops":2}')]), _assistant(content="done")]
    )
    agent = MemoryAgent(mem, lambda m, t: next(replies), tools=ToolsetConfig(params={"reason": {"max_hops": 8}}))
    agent.chat("x")
    assert mem.find_path_calls == [("a", "b", 8)]  # params 覆盖 LLM 的 2


def test_dispatch_unknown_tool_returns_error():
    mem = _Memory()
    seen: list[list[dict]] = []

    def llm(msgs, tools):
        seen.append(msgs)
        if len(seen) == 1:
            return _assistant(tool_calls=[_tc("1", "ghost", "{}")])
        tool_msgs = [m for m in msgs if m.get("role") == "tool"]
        assert any("[error]" in m["content"] and "ghost" in m["content"] for m in tool_msgs)
        return _assistant(content="ok")

    agent = MemoryAgent(mem, llm, max_turns=4)
    assert agent.chat("x") == "ok"
    assert mem.find_path_calls == []  # ghost 未触达真 memory


def test_dispatch_enabled_excludes_from_schemas():
    """enabled 限定的工具集：仅这些暴露给 LLM。"""
    mem = _Memory()
    captured: dict[str, list] = {}

    def llm(msgs, tools):
        captured["tools"] = tools
        return _assistant(content="ok")

    agent = MemoryAgent(mem, llm, tools=ToolsetConfig(enabled=["search"]))
    agent.chat("x")
    assert {t["function"]["name"] for t in captured["tools"]} == {"search"}

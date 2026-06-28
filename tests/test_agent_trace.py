"""agent-llm-trace 追踪功能测试。

覆盖：数据结构、llm_call 追踪、loop 集成、_trace 键剥离、回调异常隔离、on_trace=None。
"""

from __future__ import annotations

import dataclasses
import time
from unittest.mock import MagicMock, patch

from mcs_agent.loop import MemoryAgent
from mcs_agent.trace import (
    ChatTrace,
    LLMCallTrace,
    MessageSummary,
    TokenUsage,
    ToolCallTrace,
)


# === 5.1 trace.py 数据结构 ===


def _make_llm_trace(total_tokens: int | None = 100) -> LLMCallTrace:
    token_usage = TokenUsage(prompt_tokens=50, completion_tokens=50, total_tokens=total_tokens) if total_tokens is not None else None
    return LLMCallTrace(
        model="test-model",
        latency_ms=100.0,
        token_usage=token_usage,
        timestamp=1234.5,
        request_summary=[MessageSummary(role="user", content_preview="hi")],
        response_summary="hello",
        tool_call_names=[],
    )


def test_token_usage_fields():
    tu = TokenUsage(prompt_tokens=10, completion_tokens=20, total_tokens=30)
    assert tu.prompt_tokens == 10
    assert tu.completion_tokens == 20
    assert tu.total_tokens == 30


def test_token_usage_none_fields():
    tu = TokenUsage()
    assert tu.prompt_tokens is None
    assert tu.completion_tokens is None
    assert tu.total_tokens is None


def test_message_summary_truncation():
    ms = MessageSummary(role="user", content_preview="x" * 100)
    assert len(ms.content_preview) == 100


def test_chat_trace_total_tokens_all_present():
    trace = ChatTrace(
        user_message="hi",
        reply="hello",
        llm_calls=[_make_llm_trace(100), _make_llm_trace(200)],
        tool_calls=[],
        total_latency_ms=300.0,
    )
    assert trace.total_tokens == 300


def test_chat_trace_total_tokens_one_missing():
    trace = ChatTrace(
        user_message="hi",
        reply="hello",
        llm_calls=[_make_llm_trace(100), _make_llm_trace(None)],
        tool_calls=[],
        total_latency_ms=300.0,
    )
    assert trace.total_tokens is None


def test_chat_trace_total_tokens_usage_none():
    """LLMCallTrace.token_usage 整体为 None 时 total_tokens 为 None。"""
    trace = ChatTrace(
        user_message="hi",
        reply="hello",
        llm_calls=[_make_llm_trace(100), _make_llm_trace(None)],
        tool_calls=[],
        total_latency_ms=300.0,
    )
    assert trace.total_tokens is None


def test_chat_trace_total_tokens_empty_llm_calls():
    """无 LLM 调用记录时 total_tokens 为 None（"无记录"≠"0 token"）。"""
    trace = ChatTrace(
        user_message="hi",
        reply="hello",
        llm_calls=[],
        tool_calls=[],
        total_latency_ms=100.0,
    )
    assert trace.total_tokens is None


# === 5.2 llm.py：mock OpenAI 响应 ===


def test_llm_call_trace_with_usage():
    """make_openai_llm_call 返回的 callable 提取 usage 并构造 _trace。"""
    from mcs_agent.llm import make_openai_llm_call

    mock_usage = MagicMock()
    mock_usage.prompt_tokens = 10
    mock_usage.completion_tokens = 20
    mock_usage.total_tokens = 30

    mock_message = MagicMock()
    mock_message.model_dump.return_value = {
        "role": "assistant",
        "content": "hello",
        "tool_calls": None,
    }

    mock_choice = MagicMock()
    mock_choice.message = mock_message

    mock_resp = MagicMock()
    mock_resp.choices = [mock_choice]
    mock_resp.usage = mock_usage

    with patch("openai.OpenAI") as MockOpenAI:
        mock_client = MagicMock()
        MockOpenAI.return_value = mock_client
        mock_client.chat.completions.create.return_value = mock_resp

        llm_call = make_openai_llm_call("test-model", "fake-key")
        result = llm_call([{"role": "user", "content": "hi"}], [])

    assert "_trace" in result
    trace = result["_trace"]
    assert isinstance(trace, LLMCallTrace)
    assert trace.model == "test-model"
    assert trace.token_usage is not None
    assert trace.token_usage.total_tokens == 30
    assert trace.response_summary == "hello"
    assert len(trace.request_summary) == 1
    assert trace.request_summary[0].role == "user"
    assert trace.latency_ms > 0


def test_llm_call_trace_without_usage():
    """usage 为 None 时 token_usage 为 None，不崩溃。"""
    from mcs_agent.llm import make_openai_llm_call

    mock_message = MagicMock()
    mock_message.model_dump.return_value = {
        "role": "assistant",
        "content": "hi",
        "tool_calls": None,
    }

    mock_choice = MagicMock()
    mock_choice.message = mock_message

    mock_resp = MagicMock()
    mock_resp.choices = [mock_choice]
    mock_resp.usage = None

    with patch("openai.OpenAI") as MockOpenAI:
        mock_client = MagicMock()
        MockOpenAI.return_value = mock_client
        mock_client.chat.completions.create.return_value = mock_resp

        llm_call = make_openai_llm_call("test-model", "fake-key")
        result = llm_call([{"role": "user", "content": "hi"}], [])

    trace = result["_trace"]
    assert isinstance(trace, LLMCallTrace)
    assert trace.token_usage is None


def test_llm_call_trace_tool_call_names():
    """_trace 提取 tool_calls 名称列表。"""
    from mcs_agent.llm import make_openai_llm_call

    mock_message = MagicMock()
    mock_message.model_dump.return_value = {
        "role": "assistant",
        "content": None,
        "tool_calls": [
            {"id": "1", "type": "function", "function": {"name": "search", "arguments": '{"query":"x"}'}},
            {"id": "2", "type": "function", "function": {"name": "learn", "arguments": '{"text":"y"}'}},
        ],
    }

    mock_choice = MagicMock()
    mock_choice.message = mock_message

    mock_usage = MagicMock()
    mock_usage.prompt_tokens = 5
    mock_usage.completion_tokens = 5
    mock_usage.total_tokens = 10

    mock_resp = MagicMock()
    mock_resp.choices = [mock_choice]
    mock_resp.usage = mock_usage

    with patch("openai.OpenAI") as MockOpenAI:
        mock_client = MagicMock()
        MockOpenAI.return_value = mock_client
        mock_client.chat.completions.create.return_value = mock_resp

        llm_call = make_openai_llm_call("test-model", "fake-key")
        result = llm_call([{"role": "user", "content": "hi"}], [])

    trace = result["_trace"]
    assert trace.tool_call_names == ["search", "learn"]


def test_llm_call_trace_timestamp_is_wall_clock():
    """timestamp 应为 time.time() 墙钟时间，而非 perf_counter 单调计数器。"""
    from mcs_agent.llm import make_openai_llm_call

    before = time.time()

    mock_message = MagicMock()
    mock_message.model_dump.return_value = {
        "role": "assistant",
        "content": "hi",
        "tool_calls": None,
    }

    mock_choice = MagicMock()
    mock_choice.message = mock_message

    mock_usage = MagicMock()
    mock_usage.prompt_tokens = 1
    mock_usage.completion_tokens = 1
    mock_usage.total_tokens = 2

    mock_resp = MagicMock()
    mock_resp.choices = [mock_choice]
    mock_resp.usage = mock_usage

    with patch("openai.OpenAI") as MockOpenAI:
        mock_client = MagicMock()
        MockOpenAI.return_value = mock_client
        mock_client.chat.completions.create.return_value = mock_resp

        llm_call = make_openai_llm_call("test-model", "fake-key")
        result = llm_call([{"role": "user", "content": "hi"}], [])

    after = time.time()
    trace = result["_trace"]
    # timestamp 应在 [before, after] 墙钟时间范围内
    assert before <= trace.timestamp <= after


# === 5.3 loop.py：mock llm_call（无 _trace）验证 ChatTrace ===


class _FakeMemory:
    """暴露 7 原语的 fake memory。"""

    def learn(self, text: str) -> str:
        return f"[memory] 已写入：{text}"

    def search(self, query: str, mode: str = "keyword") -> str:
        return f"[memory] 种子：1. [id:c1] {query}"

    def associate(self, seed_id: str, mode: str = "mcs") -> str:
        return f"[memory] 从 {seed_id} 扩展"

    def find_path(self, source_id: str, target_id: str, max_hops: int = 6) -> str:
        return f"[memory] 路径：{source_id} -> {target_id}"

    def recall(self, limit: int = 5) -> str:
        return "[memory] (无热点事件)"

    def generalize(self, node_ids: list, focus: str | None = None) -> str:
        return "[memory] 概括结论"

    def arbitrate(self, node_ids: list, question: str, events_per_fact: int = 3) -> str:
        return "[memory] 裁决结论"


def _assistant(content: str | None = None, tool_calls: list[dict] | None = None) -> dict:
    msg: dict = {"role": "assistant", "content": content}
    if tool_calls:
        msg["tool_calls"] = tool_calls
    return msg


def _tc(call_id: str, name: str, args: str) -> dict:
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": args},
    }


def test_chat_trace_with_mock_llm_no_trace():
    """mock llm_call 不含 _trace 时，ChatTrace.llm_calls 为空但仍记录 tool_calls。"""
    memory = _FakeMemory()
    traces: list[ChatTrace] = []

    def on_trace(ct: ChatTrace) -> None:
        traces.append(ct)

    replies = iter([
        _assistant(tool_calls=[_tc("1", "search", '{"query": "test"}')]),
        _assistant(content="结果"),
    ])
    agent = MemoryAgent(memory, lambda m, t: next(replies), on_trace=on_trace)
    reply = agent.chat("test")

    assert reply == "结果"
    assert len(traces) == 1
    ct = traces[0]
    assert ct.llm_calls == []  # mock 无 _trace
    assert len(ct.tool_calls) == 1
    assert ct.tool_calls[0].tool_name == "search"
    assert ct.tool_calls[0].error is None
    assert ct.total_latency_ms > 0


def test_chat_trace_with_llm_trace():
    """llm_call 含 _trace 时，ChatTrace.llm_calls 完整记录。"""
    memory = _FakeMemory()
    traces: list[ChatTrace] = []

    def on_trace(ct: ChatTrace) -> None:
        traces.append(ct)

    llm_trace = _make_llm_trace(100)

    def llm(messages, tools):
        r = _assistant(content="答完了")
        r["_trace"] = llm_trace
        return r

    agent = MemoryAgent(memory, llm, on_trace=on_trace)
    agent.chat("hi")

    assert len(traces) == 1
    ct = traces[0]
    assert len(ct.llm_calls) == 1
    assert ct.llm_calls[0] is llm_trace


def test_chat_trace_tool_exception():
    """工具异常时 ToolCallTrace.error 非空。"""
    traces: list[ChatTrace] = []

    def on_trace(ct: ChatTrace) -> None:
        traces.append(ct)

    class BadMemory:
        def search(self, q, mode="keyword"):
            raise RuntimeError("boom")

        def learn(self, t):
            return "ok"

        def associate(self, s, mode="mcs"):
            return "ok"

        def find_path(self, s, t, max_hops=6):
            return "ok"

        def recall(self, limit=5):
            return "ok"

    replies = iter([
        _assistant(tool_calls=[_tc("1", "search", '{"query": "q"}')]),
        _assistant(content="ok"),
    ])
    agent = MemoryAgent(BadMemory(), lambda m, t: next(replies), on_trace=on_trace)
    agent.chat("q")

    ct = traces[0]
    assert len(ct.tool_calls) == 1
    assert ct.tool_calls[0].tool_name == "search"
    assert ct.tool_calls[0].error is not None
    assert "RuntimeError" in ct.tool_calls[0].error
    assert "boom" in ct.tool_calls[0].error
    assert "[error]" in ct.tool_calls[0].result_summary


# === 5.4 _trace 键剥离 ===


def test_trace_key_stripped_from_messages():
    """追加到 messages 的 dict 不含 _trace 键。"""
    memory = _FakeMemory()
    captured_messages: list[list[dict]] = []

    def llm(messages, tools):
        captured_messages.append(messages)
        r = _assistant(content="done")
        r["_trace"] = _make_llm_trace(50)
        return r

    agent = MemoryAgent(memory, llm)
    agent.chat("hi")

    # 第二次 llm_call 时收到的 messages 应不含 _trace
    for msgs in captured_messages:
        for msg in msgs:
            assert "_trace" not in msg


def test_trace_key_stripped_with_tool_calls():
    """tool_calls 场景下 _trace 也被剥离。"""
    memory = _FakeMemory()
    captured_messages: list[list[dict]] = []

    def llm(messages, tools):
        captured_messages.append(messages)
        if len(messages) <= 2:
            r = _assistant(tool_calls=[_tc("1", "search", '{"query": "q"}')])
            r["_trace"] = _make_llm_trace(50)
            return r
        r = _assistant(content="done")
        r["_trace"] = _make_llm_trace(30)
        return r

    agent = MemoryAgent(memory, llm)
    agent.chat("q")

    for msgs in captured_messages:
        for msg in msgs:
            assert "_trace" not in msg


# === 5.5 on_trace 回调异常隔离 ===


def test_on_trace_exception_does_not_affect_chat():
    """on_trace 回调抛异常时 chat() 仍正常返回。"""
    memory = _FakeMemory()

    def bad_callback(ct: ChatTrace) -> None:
        raise ValueError("callback boom")

    agent = MemoryAgent(memory, lambda m, t: _assistant(content="ok"), on_trace=bad_callback)
    reply = agent.chat("hi")
    assert reply == "ok"


# === 5.6 on_trace=None 时静默无副作用 ===


def test_on_trace_none_no_side_effects():
    """on_trace=None 时 chat() 正常工作，无任何追踪副作用。"""
    memory = _FakeMemory()
    agent = MemoryAgent(memory, lambda m, t: _assistant(content="ok"))
    reply = agent.chat("hi")
    assert reply == "ok"


def test_chat_trace_serializable():
    """ChatTrace 可通过 dataclasses.asdict 序列化为 dict。"""
    trace = ChatTrace(
        user_message="hi",
        reply="hello",
        llm_calls=[_make_llm_trace(100)],
        tool_calls=[ToolCallTrace(tool_name="search", args_summary='{"query":"x"}', result_summary="ok", latency_ms=5.0, error=None)],
        total_latency_ms=200.0,
    )
    d = dataclasses.asdict(trace)
    assert isinstance(d, dict)
    assert d["user_message"] == "hi"
    assert len(d["llm_calls"]) == 1
    assert d["llm_calls"][0]["token_usage"]["total_tokens"] == 100
    assert len(d["tool_calls"]) == 1
    assert d["tool_calls"][0]["tool_name"] == "search"
    assert d["total_tokens"] == 100


def test_tool_call_trace_bad_json_args():
    """非法 JSON 参数时 ToolCallTrace.error 非空。"""
    traces: list[ChatTrace] = []

    def on_trace(ct: ChatTrace) -> None:
        traces.append(ct)

    memory = _FakeMemory()
    replies = iter([
        _assistant(tool_calls=[_tc("1", "search", "不是json")]),
        _assistant(content="ok"),
    ])
    agent = MemoryAgent(memory, lambda m, t: next(replies), on_trace=on_trace)
    agent.chat("x")

    ct = traces[0]
    assert len(ct.tool_calls) == 1
    assert ct.tool_calls[0].error is not None
    assert "JSON" in ct.tool_calls[0].error
    assert "[error]" in ct.tool_calls[0].result_summary


def test_tool_call_trace_unknown_tool():
    """未知工具时 ToolCallTrace.error 非空。"""
    traces: list[ChatTrace] = []

    def on_trace(ct: ChatTrace) -> None:
        traces.append(ct)

    memory = _FakeMemory()
    replies = iter([
        _assistant(tool_calls=[_tc("1", "delete_all", '{"x": "1"}')]),
        _assistant(content="ok"),
    ])
    agent = MemoryAgent(memory, lambda m, t: next(replies), on_trace=on_trace)
    agent.chat("x")

    ct = traces[0]
    assert len(ct.tool_calls) == 1
    assert ct.tool_calls[0].error is not None
    assert "未知工具" in ct.tool_calls[0].error


def test_chat_trace_user_message_and_reply_truncation():
    """user_message 和 reply 超长时截断。"""
    memory = _FakeMemory()
    traces: list[ChatTrace] = []

    def on_trace(ct: ChatTrace) -> None:
        traces.append(ct)

    long_msg = "字" * 200
    long_reply = "答" * 300
    agent = MemoryAgent(memory, lambda m, t: _assistant(content=long_reply), on_trace=on_trace)
    agent.chat(long_msg)

    ct = traces[0]
    assert len(ct.user_message) <= 100
    assert len(ct.reply) <= 200

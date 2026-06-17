"""记忆 agent loop 的测试。

mock LLM（脚本化 callable）+ fake memory，不依赖真实 API / 真实 MCS。
覆盖：直接作答、query→答、ingest、max_turns 兜底、工具异常隔离、未知工具、坏 JSON。
另有 MemoryStore 的轻量转发测试（fake mcs，验证单线程转发 + 渲染）。
"""

from __future__ import annotations

from mcs.agent.loop import MemoryAgent
from mcs.agent.memory import MemoryStore


# === fake memory（只暴露 query/ingest，供 loop 测试） ===


class FakeMemory:
    def __init__(self) -> None:
        self.query_calls: list[str] = []
        self.ingest_calls: list[str] = []

    def query(self, query: str) -> str:
        self.query_calls.append(query)
        return f"[memory] 关于「{query}」的检索结果"

    def ingest(self, text: str) -> str:
        self.ingest_calls.append(text)
        return f"[memory] 已写入：{text}"


# === openai 消息格式构造辅助 ===


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


# === loop 测试 ===


def test_no_tool_direct_answer():
    memory = FakeMemory()
    llm = lambda msgs, tools: _assistant(content="你好。")  # noqa: E731
    agent = MemoryAgent(memory, llm, max_turns=4)
    assert agent.chat("你好") == "你好。"
    assert memory.query_calls == []


def test_query_then_answer():
    memory = FakeMemory()
    replies = iter(
        [
            _assistant(tool_calls=[_tc("1", "memory_query", '{"query": "深度学习"}')]),
            _assistant(content="根据记忆，深度学习是……"),
        ]
    )
    agent = MemoryAgent(memory, lambda m, t: next(replies), max_turns=4)
    assert agent.chat("什么是深度学习") == "根据记忆，深度学习是……"
    assert memory.query_calls == ["深度学习"]


def test_ingest_tool():
    memory = FakeMemory()
    replies = iter(
        [
            _assistant(tool_calls=[_tc("1", "memory_ingest", '{"text": "明天开会"}')]),
            _assistant(content="好的，已记住。"),
        ]
    )
    agent = MemoryAgent(memory, lambda m, t: next(replies), max_turns=4)
    assert agent.chat("记住明天开会") == "好的，已记住。"
    assert memory.ingest_calls == ["明天开会"]


def test_max_turns_fallback():
    memory = FakeMemory()
    # 一直调工具，永不给最终答案
    def llm(m, t):
        return _assistant(tool_calls=[_tc("x", "memory_query", '{"query": "q"}')])

    agent = MemoryAgent(memory, llm, max_turns=3)
    result = agent.chat("无限工具")
    assert "最大轮次" in result
    assert len(memory.query_calls) == 3  # 跑满 3 轮


def test_tool_exception_isolated():
    class BadMemory:
        def query(self, q):
            raise RuntimeError("boom")

        def ingest(self, t):
            raise RuntimeError("boom")

    replies = iter(
        [
            _assistant(tool_calls=[_tc("1", "memory_query", '{"query": "q"}')]),
            _assistant(content="记忆查询失败，我不知道。"),
        ]
    )
    agent = MemoryAgent(BadMemory(), lambda m, t: next(replies), max_turns=4)
    assert agent.chat("问") == "记忆查询失败，我不知道。"  # 异常被隔离为 [error] 文本，loop 继续


def test_unknown_tool():
    memory = FakeMemory()
    replies = iter(
        [
            _assistant(tool_calls=[_tc("1", "memory_delete", '{"x": "1"}')]),
            _assistant(content="done"),
        ]
    )
    agent = MemoryAgent(memory, lambda m, t: next(replies), max_turns=4)
    assert agent.chat("x") == "done"
    assert memory.query_calls == []  # 未知工具未触达真 memory


def test_bad_json_args():
    memory = FakeMemory()
    replies = iter(
        [
            _assistant(tool_calls=[_tc("1", "memory_query", "不是json")]),
            _assistant(content="ok"),
        ]
    )
    agent = MemoryAgent(memory, lambda m, t: next(replies), max_turns=4)
    assert agent.chat("x") == "ok"
    assert memory.query_calls == []  # 参数解析失败，未调真工具


def test_query_result_passed_back_to_llm():
    """工具结果作为 tool message 回传，LLM 第二轮能拿到它。"""
    memory = FakeMemory()
    seen_args: list[list[dict]] = []

    def llm(messages, tools):
        seen_args.append(messages)
        if len(seen_args) == 1:
            return _assistant(tool_calls=[_tc("1", "memory_query", '{"query": "猫"}')])
        # 第二轮：验证上一轮 tool 结果在 messages 里
        tool_msgs = [m for m in messages if m.get("role") == "tool"]
        assert any("猫" in m["content"] for m in tool_msgs)
        return _assistant(content="答完了")

    agent = MemoryAgent(memory, llm, max_turns=4)
    assert agent.chat("猫？") == "答完了"


# === MemoryStore 轻量转发测试（fake mcs，验证单线程转发 + 渲染） ===


class _FakeQE:
    relation_model = "property_graph"


class _FakeWriteCtx:
    def __init__(self) -> None:
        self.changed = [1, 2]
        self.concepts = [1]
        self.persisted = True


class FakeMCS:
    """模拟 MCS：query 返回 str（_render_query_result 原样透传）、ingest 返回 WriteCtx。"""

    query_engine = _FakeQE()
    read_manager = None

    def query(self, text: str) -> str:
        return f"raw-query-result:{text}"

    def ingest(self, text: str) -> _FakeWriteCtx:
        return _FakeWriteCtx()

    def shutdown(self) -> None:
        pass


def test_memory_store_query_renders_and_serializes():
    store = MemoryStore(FakeMCS)  # build_fn 返回 FakeMCS 实例
    try:
        assert store.query("你好") == "raw-query-result:你好"  # str 原样透传
    finally:
        store.shutdown()


def test_memory_store_ingest_status():
    store = MemoryStore(FakeMCS)
    try:
        status = store.ingest("一段记忆")
        assert "已写入" in status
        assert "persisted=yes" in status
    finally:
        store.shutdown()

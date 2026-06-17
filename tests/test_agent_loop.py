"""记忆 agent loop 的测试。

mock LLM（脚本化 callable）+ fake memory，不依赖真实 API / 真实 MCS。
覆盖：直接作答、search→答、learn、多步 id 传递（search→associate→reason）、
模式默认、max_turns 兜底、工具异常隔离、未知工具、坏 JSON、结果回灌 LLM。
"""

from __future__ import annotations

from mcs_agent.loop import MemoryAgent


# === fake memory（暴露 5 原语，供 loop 测试） ===


class FakeMemory:
    def __init__(self) -> None:
        self.learn_calls: list[str] = []
        self.search_calls: list[tuple[str, str]] = []
        self.associate_calls: list[tuple[str, str]] = []
        self.find_path_calls: list[tuple[str, str]] = []
        self.recall_calls: list[int] = []

    def learn(self, text: str) -> str:
        self.learn_calls.append(text)
        return f"[memory] 已写入：{text}"

    def search(self, query: str, mode: str = "keyword") -> str:
        self.search_calls.append((query, mode))
        return f"[memory] 种子（{mode}）：1. [id:c1] {query}"

    def associate(self, seed_id: str, mode: str = "mcs") -> str:
        self.associate_calls.append((seed_id, mode))
        return f"[memory] 从 {seed_id} 扩展：2. [id:c2] 相关"

    def find_path(self, source_id: str, target_id: str, max_hops: int = 6) -> str:
        self.find_path_calls.append((source_id, target_id))
        return f"[memory] 路径：{source_id} -> {target_id}"

    def recall(self, limit: int = 5) -> str:
        self.recall_calls.append(limit)
        return "[memory] (无热点事件)"


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
    assert memory.search_calls == []


def test_search_then_answer():
    memory = FakeMemory()
    replies = iter(
        [
            _assistant(tool_calls=[_tc("1", "search", '{"query": "深度学习", "mode": "keyword"}')]),
            _assistant(content="根据记忆，深度学习是……"),
        ]
    )
    agent = MemoryAgent(memory, lambda m, t: next(replies), max_turns=4)
    assert agent.chat("什么是深度学习") == "根据记忆，深度学习是……"
    assert memory.search_calls == [("深度学习", "keyword")]


def test_learn_tool():
    memory = FakeMemory()
    replies = iter(
        [
            _assistant(tool_calls=[_tc("1", "learn", '{"text": "明天开会"}')]),
            _assistant(content="好的，已记住。"),
        ]
    )
    agent = MemoryAgent(memory, lambda m, t: next(replies), max_turns=4)
    assert agent.chat("记住明天开会") == "好的，已记住。"
    assert memory.learn_calls == ["明天开会"]


def test_multi_step_search_associate():
    """多步导航：search 拿 [id:c1] → associate 用该 id 扩展。"""
    memory = FakeMemory()
    replies = iter(
        [
            _assistant(tool_calls=[_tc("1", "search", '{"query": "量子力学"}')]),
            _assistant(tool_calls=[_tc("2", "associate", '{"seed_id": "c1", "mode": "mcs"}')]),
            _assistant(content="综合来看……"),
        ]
    )
    agent = MemoryAgent(memory, lambda m, t: next(replies), max_turns=6)
    assert agent.chat("讲讲量子力学") == "综合来看……"
    assert memory.search_calls == [("量子力学", "keyword")]
    assert memory.associate_calls == [("c1", "mcs")]


def test_reason_find_path():
    memory = FakeMemory()
    replies = iter(
        [
            _assistant(tool_calls=[_tc("1", "reason", '{"source_id": "c1", "target_id": "c2"}')]),
            _assistant(content="两者关联路径已找到。"),
        ]
    )
    agent = MemoryAgent(memory, lambda m, t: next(replies), max_turns=4)
    assert agent.chat("c1 和 c2 的关系") == "两者关联路径已找到。"
    assert memory.find_path_calls == [("c1", "c2")]


def test_search_mode_default_keyword():
    """search 不传 mode 时默认 keyword。"""
    memory = FakeMemory()
    replies = iter(
        [
            _assistant(tool_calls=[_tc("1", "search", '{"query": "x"}')]),
            _assistant(content="ok"),
        ]
    )
    agent = MemoryAgent(memory, lambda m, t: next(replies), max_turns=4)
    agent.chat("x")
    assert memory.search_calls == [("x", "keyword")]


def test_max_turns_fallback():
    memory = FakeMemory()

    def llm(m, t):
        return _assistant(tool_calls=[_tc("x", "search", '{"query": "q"}')])

    agent = MemoryAgent(memory, llm, max_turns=3)
    result = agent.chat("无限工具")
    assert "最大轮次" in result
    assert len(memory.search_calls) == 3  # 跑满 3 轮


def test_tool_exception_isolated():
    class BadMemory:
        def search(self, q, mode="keyword"):
            raise RuntimeError("boom")

        def learn(self, t):
            raise RuntimeError("boom")

        def associate(self, s, mode="mcs"):
            raise RuntimeError("boom")

        def find_path(self, s, t, max_hops=6):
            raise RuntimeError("boom")

        def recall(self, limit=5):
            raise RuntimeError("boom")

    replies = iter(
        [
            _assistant(tool_calls=[_tc("1", "search", '{"query": "q"}')]),
            _assistant(content="检索失败，不知道。"),
        ]
    )
    agent = MemoryAgent(BadMemory(), lambda m, t: next(replies), max_turns=4)
    assert agent.chat("问") == "检索失败，不知道。"  # 异常隔离为 [error]，loop 继续


def test_unknown_tool():
    memory = FakeMemory()
    replies = iter(
        [
            _assistant(tool_calls=[_tc("1", "delete_all", '{"x": "1"}')]),
            _assistant(content="done"),
        ]
    )
    agent = MemoryAgent(memory, lambda m, t: next(replies), max_turns=4)
    assert agent.chat("x") == "done"
    assert memory.search_calls == []  # 未知工具未触达真 memory


def test_bad_json_args():
    memory = FakeMemory()
    replies = iter(
        [
            _assistant(tool_calls=[_tc("1", "search", "不是json")]),
            _assistant(content="ok"),
        ]
    )
    agent = MemoryAgent(memory, lambda m, t: next(replies), max_turns=4)
    assert agent.chat("x") == "ok"
    assert memory.search_calls == []  # 参数解析失败，未调真工具


def test_result_passed_back_to_llm():
    """工具结果作为 tool message 回传，LLM 第二轮能拿到它。"""
    memory = FakeMemory()
    seen: list[list[dict]] = []

    def llm(messages, tools):
        seen.append(messages)
        if len(seen) == 1:
            return _assistant(tool_calls=[_tc("1", "search", '{"query": "猫"}')])
        tool_msgs = [m for m in messages if m.get("role") == "tool"]
        assert any("猫" in m["content"] for m in tool_msgs)
        return _assistant(content="答完了")

    agent = MemoryAgent(memory, llm, max_turns=4)
    assert agent.chat("猫？") == "答完了"

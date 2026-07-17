"""agent 会话上下文自治（change agent-context-autonomy）的测试。

注入式 fake LLM（脚本化 callable，捕获每轮发送视图）+ fake memory + ``len`` 作
确定性 token 计数。覆盖：

- 阶段 A：折叠触发 / 幂等 / 不折叠 assistant / 窗口级 id 去重且首见不丢 /
  同参标注不拦截 / 默认关闭零变化 / 预算段注入。
- 阶段 B：pin 不被折叠（含恢复已折叠全文）/ unpin 后可折叠 / pin 上限拒绝 /
  兜底链（全量折叠 → 逐出墓碑）/ 拒绝注入后可收尾 / FINISH 剥离与终止类型 /
  implicit 宽松接受 / forced 超轮次。
"""

from __future__ import annotations

from mcs_agent.context import CONTEXT_MANAGEMENT_PROMPT
from mcs_agent.loop import MemoryAgent
from mcs_agent.trace import ChatTrace


# === fakes ===


class Mem:
    """fake memory：search / associate 返回带 [id:...] 的可控文本。"""

    def __init__(self) -> None:
        self.search_calls: list[str] = []
        self.associate_calls: list[str] = []

    def search(self, query: str, mode: str = "keyword", universe: str = "__reality__") -> str:
        self.search_calls.append(query)
        # 内容加长到贴近真实渲染尺寸——折叠只在存根比全文短时发生（优化判据）
        pad = "描" * 120
        return f"[memory] 种子：1. [id:{query}1] {query}甲 — {pad} 2. [id:{query}2] {query}乙"

    def associate(self, seed_id: str, mode: str = "mcs") -> str:
        self.associate_calls.append(seed_id)
        pad = "述" * 120
        return f"[memory] 扩展：1. [id:{seed_id}] 回看 — {pad} 2. [id:x9] 新节点"


def _assistant(content: str | None = None, tool_calls: list[dict] | None = None) -> dict:
    msg: dict = {"role": "assistant", "content": content}
    if tool_calls:
        msg["tool_calls"] = tool_calls
    return msg


def _tc(call_id: str, name: str, args: str) -> dict:
    return {"id": call_id, "type": "function", "function": {"name": name, "arguments": args}}


def _make_llm(replies: list[dict]):
    """脚本化 LLM：按序出脚本回复，捕获每轮收到的发送视图。"""
    sent: list[list[dict]] = []
    it = iter(replies)

    def llm(messages: list[dict], tools: list[dict]) -> dict:
        sent.append([dict(m) for m in messages])
        return next(it)

    return llm, sent


def _agent(memory, llm, *, budget=100_000, on_trace=None, **kw) -> MemoryAgent:
    """预算开启的 agent，system_prompt 极小 + len 计数（尺寸可控可算）。"""
    return MemoryAgent(
        memory,
        llm,
        system_prompt="S",
        max_turns=6,
        context_budget=budget,
        token_counter=len,
        on_trace=on_trace,
        **kw,
    )


def _tool_msgs(view: list[dict]) -> list[dict]:
    return [m for m in view if m.get("role") == "tool"]


# === 阶段 A：存根折叠 + 预算可见（减脂层）===


def test_fold_after_n_turns_keeps_recent_full():
    """≥N 轮的未 pin 工具结果折叠为存根（含全量 id）；近轮与 assistant/user 不折叠。"""
    memory = Mem()
    llm, sent = _make_llm(
        [
            _assistant(content="查A", tool_calls=[_tc("1", "search", '{"query": "A"}')]),
            _assistant(tool_calls=[_tc("2", "search", '{"query": "B"}')]),
            _assistant(content="答完"),
        ]
    )
    agent = _agent(memory, llm, fold_after_turns=2)
    assert agent.chat("问") == "答完"

    turn2 = sent[2]
    tools = _tool_msgs(turn2)
    assert len(tools) == 2
    # turn0 的结果（距今 2 轮）折叠：一行存根、保留全部触达 id
    assert tools[0]["content"].startswith("[已折叠 #1] search")
    assert "[id:A1]" in tools[0]["content"] and "[id:A2]" in tools[0]["content"]
    # turn1 的结果（距今 1 轮 < N=2）保持全文
    assert tools[1]["content"].startswith("[memory] 种子")
    # assistant / user 消息不折叠
    assert any(m.get("role") == "assistant" and m.get("content") == "查A" for m in turn2)
    assert any(m.get("role") == "user" and m.get("content") == "问" for m in turn2)


def test_fold_idempotent_across_turns():
    """折叠每轮从原始历史重算：同一存根行逐轮稳定（幂等），原文不受污染。"""
    memory = Mem()
    llm, sent = _make_llm(
        [
            _assistant(tool_calls=[_tc("1", "search", '{"query": "A"}')]),
            _assistant(tool_calls=[_tc("2", "search", '{"query": "B"}')]),
            _assistant(tool_calls=[_tc("3", "search", '{"query": "C"}')]),
            _assistant(content="ok"),
        ]
    )
    agent = _agent(memory, llm, fold_after_turns=2)
    agent.chat("问")
    stub_t2 = _tool_msgs(sent[2])[0]["content"]
    stub_t3 = _tool_msgs(sent[3])[0]["content"]
    assert stub_t2 == stub_t3  # 重算幂等
    assert stub_t2.startswith("[已折叠 #1]")


def test_window_level_id_dedup_first_seen_kept():
    """窗口级 id 去重：首见全文列出、已见计数省略；首见 id 决不丢。"""
    memory = Mem()
    # associate("A1") 返回 [id:A1]（与存根 #1 重复）+ [id:x9]（新见）
    llm, sent = _make_llm(
        [
            _assistant(tool_calls=[_tc("1", "search", '{"query": "A"}')]),
            _assistant(tool_calls=[_tc("2", "associate", '{"seed_id": "A1"}')]),
            _assistant(tool_calls=[_tc("3", "search", '{"query": "D"}')]),
            _assistant(content="ok"),
        ]
    )
    agent = _agent(memory, llm, fold_after_turns=1)
    agent.chat("问")
    tools = _tool_msgs(sent[3])
    stub1, stub2 = tools[0]["content"], tools[1]["content"]
    assert "[id:A1]" in stub1  # 首见在最早存根
    assert "[id:x9]" in stub2  # 本存根的新 id 保留
    assert "[id:A1]" not in stub2  # 已见 id 不重复列
    assert "(+1 已见)" in stub2


def test_same_args_annotated_not_intercepted():
    """同参重复调用：正常执行（不拦截不缓存），仅结果头部标注同参存根 + dup_call 事件。"""
    memory = Mem()
    traces: list[ChatTrace] = []
    llm, sent = _make_llm(
        [
            _assistant(tool_calls=[_tc("1", "search", '{"query": "A"}')]),
            _assistant(tool_calls=[_tc("2", "search", '{"query": "A"}')]),
            _assistant(content="ok"),
        ]
    )
    agent = _agent(memory, llm, on_trace=traces.append)
    agent.chat("问")
    assert memory.search_calls == ["A", "A"]  # 工具真的执行了两次
    second = _tool_msgs(sent[2])[1]["content"]
    assert second.startswith("（与存根 #1 同参）\n")
    assert "[memory] 种子" in second  # 全文注入，未被缓存/截断
    dups = [e for e in traces[0].context_events if e.kind == "dup_call"]
    assert len(dups) == 1 and dups[0].stub_no == 1
    assert "pin集未变" in dups[0].detail  # 无 pin 变化的同参重发 = 盲目重复（观测口径）


def test_default_off_zero_change():
    """context_budget 未设置：不折叠、无预算段、标记不解析、trace 无上下文事件。"""
    memory = Mem()
    traces: list[ChatTrace] = []
    llm, sent = _make_llm(
        [
            _assistant(tool_calls=[_tc("1", "search", '{"query": "A"}')]),
            _assistant(tool_calls=[_tc("2", "search", '{"query": "A"}')]),
            _assistant(tool_calls=[_tc("3", "search", '{"query": "B"}')]),
            _assistant(content="答\nFINISH\nUSED: #1"),
        ]
    )
    agent = MemoryAgent(memory, llm, max_turns=6, on_trace=traces.append)
    reply = agent.chat("问")
    assert reply == "答\nFINISH\nUSED: #1"  # 标记不剥离（未开启零变化）
    last = sent[-1]
    assert all("[已折叠" not in (m.get("content") or "") for m in last)
    assert all("（与存根" not in (m.get("content") or "") for m in last)
    assert "# 会话预算" not in last[0]["content"]
    assert CONTEXT_MANAGEMENT_PROMPT not in last[0]["content"]
    assert traces[0].context_events == []
    assert traces[0].termination == "implicit"


def test_budget_section_and_management_prompt_injected():
    """预算开启：system 注入管理约定段 + 每轮动态预算段（已用/剩余、剩余轮次）。"""
    memory = Mem()
    llm, sent = _make_llm(
        [
            _assistant(tool_calls=[_tc("1", "search", '{"query": "A"}')]),
            _assistant(content="ok"),
        ]
    )
    _agent(memory, llm).chat("问")
    for view in sent:
        sys = view[0]["content"]
        assert "# 会话上下文管理" in sys
        assert "# 会话预算" in sys and "剩余轮次" in sys
    # 剩余轮次逐轮递减
    assert "剩余轮次 6" in sent[0][0]["content"]
    assert "剩余轮次 5" in sent[1][0]["content"]


def test_fold_event_traced():
    """折叠事件入 ChatTrace（首折记一次，含前后 token）。"""
    memory = Mem()
    traces: list[ChatTrace] = []
    llm, _ = _make_llm(
        [
            _assistant(tool_calls=[_tc("1", "search", '{"query": "A"}')]),
            _assistant(tool_calls=[_tc("2", "search", '{"query": "B"}')]),
            _assistant(tool_calls=[_tc("3", "search", '{"query": "C"}')]),
            _assistant(content="ok"),
        ]
    )
    _agent(memory, llm, fold_after_turns=1, on_trace=traces.append).chat("问")
    folds = [e for e in traces[0].context_events if e.kind == "fold"]
    # N=1：三条结果在末轮均到龄折叠；每条只记一次（幂等重算不重复记）
    assert [e.stub_no for e in folds] == [1, 2, 3]
    assert all(e.tokens_before > e.tokens_after for e in folds)


# === 阶段 B：pin / 兜底 / FINISH（自治层）===


def test_pin_prevents_fold_and_restores_folded():
    """pin 项不折叠；对已折叠存根 PIN 恢复其全文（原始历史未改写——遗忘可逆）。"""
    memory = Mem()
    llm, sent = _make_llm(
        [
            _assistant(tool_calls=[_tc("1", "search", '{"query": "A"}')]),
            _assistant(tool_calls=[_tc("2", "search", '{"query": "B"}')]),
            _assistant(content="PIN: #1", tool_calls=[_tc("3", "search", '{"query": "C"}')]),
            _assistant(content="ok"),
        ]
    )
    agent = _agent(memory, llm, fold_after_turns=1)
    agent.chat("问")
    # turn2 发送时 #1 已折叠（PIN 在 turn2 回复里才声明）
    assert _tool_msgs(sent[2])[0]["content"].startswith("[已折叠 #1]")
    # turn3：#1 被 pin → 恢复全文；#2 未 pin → 折叠
    tools = _tool_msgs(sent[3])
    assert tools[0]["content"].startswith("[memory] 种子")
    assert tools[1]["content"].startswith("[已折叠 #2]")


def test_unpin_allows_fold_again():
    """UNPIN 换出后重新可折叠。PIN 在 #1 注册后的轮次声明（先于注册的编号引用被忽略）。"""
    memory = Mem()
    llm, sent = _make_llm(
        [
            _assistant(tool_calls=[_tc("1", "search", '{"query": "A"}')]),
            _assistant(content="PIN: #1", tool_calls=[_tc("2", "search", '{"query": "B"}')]),
            _assistant(content="UNPIN: #1", tool_calls=[_tc("3", "search", '{"query": "C"}')]),
            _assistant(tool_calls=[_tc("4", "search", '{"query": "D"}')]),
            _assistant(content="ok"),
        ]
    )
    agent = _agent(memory, llm, fold_after_turns=1)
    agent.chat("问")
    # turn2 发送：#1 pinned → 全文
    assert _tool_msgs(sent[2])[0]["content"].startswith("[memory] 种子")
    # turn3 发送：#1 已 UNPIN → 重新可折叠
    assert _tool_msgs(sent[3])[0]["content"].startswith("[已折叠 #1]")


def test_pin_cap_rejects_and_traces():
    """pin 总量防御上限：超限的 PIN 被拒绝（trace 记 pin_rejected），项仍可折叠。"""
    memory = Mem()
    traces: list[ChatTrace] = []
    llm, sent = _make_llm(
        [
            _assistant(tool_calls=[_tc("1", "search", '{"query": "A"}')]),
            _assistant(content="PIN: #1", tool_calls=[_tc("2", "search", '{"query": "B"}')]),
            _assistant(tool_calls=[_tc("3", "search", '{"query": "C"}')]),
            _assistant(content="ok"),
        ]
    )
    agent = _agent(memory, llm, fold_after_turns=1, pin_cap_ratio=0.0, on_trace=traces.append)
    agent.chat("问")
    assert any(e.kind == "pin_rejected" and e.stub_no == 1 for e in traces[0].context_events)
    assert not any(e.kind == "pin" for e in traces[0].context_events)
    # 拒绝后 #1 照常折叠
    assert _tool_msgs(sent[3])[0]["content"].startswith("[已折叠 #1]")


def test_fallback_chain_emergency_fold_then_evict():
    """兜底链：超预算 → 全量折叠（含近轮）→ 仍超 → 逐出最旧未 pin 存根（墓碑）；不死锁。"""

    class BigMem(Mem):
        def search(self, query: str, mode: str = "keyword", universe: str = "__reality__") -> str:
            self.search_calls.append(query)
            ids = " ".join(f"[id:{query}{i:02d}]" for i in range(30))
            return f"[memory] 种子：{ids} — {'详' * 600}"

    memory = BigMem()
    traces: list[ChatTrace] = []
    llm, sent = _make_llm(
        [
            _assistant(tool_calls=[_tc("1", "search", '{"query": "A"}')]),
            _assistant(tool_calls=[_tc("2", "search", '{"query": "B"}')]),
            _assistant(content="ok"),
        ]
    )
    # 预算 = 底座 + 500：每条结果 ~900 字符、存根 ~340。turn1 紧急折叠 #1 后放得下；
    # turn2 两条存根 ~680 + assistants 仍超 → 逐出 #1 → 放得下（不死锁）
    base = len(f"S\n\n# 当前记忆图主题\n(尚未生成)\n\n{CONTEXT_MANAGEMENT_PROMPT}") + len("问")
    agent = _agent(memory, llm, budget=base + 500, on_trace=traces.append)
    assert agent.chat("问") == "ok"  # 正常收尾——MUST NOT 死锁
    tools = _tool_msgs(sent[2])
    assert tools[0]["content"] == "[已逐出 #1]"
    assert tools[1]["content"].startswith("[已折叠 #2]")
    kinds = [e.kind for e in traces[0].context_events]
    assert "fold" in kinds and "evict" in kinds


def test_exhausted_rejects_injection_then_finish():
    """pin/底座超预算：拒绝执行并注入 [预算耗尽] tool 消息，模型仍可 FINISH 收尾。"""
    memory = Mem()
    traces: list[ChatTrace] = []
    llm, sent = _make_llm(
        [
            _assistant(tool_calls=[_tc("1", "search", '{"query": "A"}')]),
            _assistant(content="记忆无从查证。\nFINISH"),
        ]
    )
    agent = _agent(memory, llm, budget=50, on_trace=traces.append)  # 底座即超预算
    reply = agent.chat("问")
    assert reply == "记忆无从查证。"
    assert memory.search_calls == []  # 拒绝注入 = 不执行工具
    assert "[预算耗尽]" in _tool_msgs(sent[1])[0]["content"]
    kinds = [e.kind for e in traces[0].context_events]
    assert "overflow" in kinds and "reject" in kinds
    assert traces[0].termination == "finish"


def test_finish_stripped_and_traced():
    """FINISH 收束：剥离标记返回答案；终止类型与 USED 引用入 trace。"""
    memory = Mem()
    traces: list[ChatTrace] = []
    llm, _ = _make_llm(
        [
            _assistant(tool_calls=[_tc("1", "search", '{"query": "A"}')]),
            _assistant(content="答案是 X。\nPIN: #1\nFINISH\nUSED: #1 [id:A1]"),
        ]
    )
    reply = _agent(memory, llm, on_trace=traces.append).chat("问")
    assert reply == "答案是 X。"  # PIN/FINISH/USED 行全部剥离
    assert traces[0].termination == "finish"
    assert traces[0].used_refs == ["#1", "[id:A1]"]


def test_implicit_accepted_without_marker():
    """无标记且无工具调用：宽松接受为最终答复，终止类型 implicit。"""
    memory = Mem()
    traces: list[ChatTrace] = []
    llm, _ = _make_llm([_assistant(content="直接答。")])
    reply = _agent(memory, llm, on_trace=traces.append).chat("问")
    assert reply == "直接答。"
    assert traces[0].termination == "implicit"


def test_last_turn_directive_injected():
    """剩余 1 轮时预算段替换为「最后一轮请直接作答」收尾指令（D5）。"""
    memory = Mem()
    llm, sent = _make_llm(
        [
            _assistant(tool_calls=[_tc("1", "search", '{"query": "A"}')]),
            _assistant(content="答。"),
        ]
    )
    MemoryAgent(memory, llm, system_prompt="S", max_turns=2,
                context_budget=100_000, token_counter=len).chat("问")
    assert "剩余轮次" in sent[0][0]["content"]  # 首轮：常规预算段
    assert "最后一轮" in sent[1][0]["content"]  # 末轮：收尾指令


def test_finalize_turn_delivers_after_max_turns():
    """轮次耗尽 → 收尾轮硬指令再调一次：交付答案 + USED，termination=finalized。"""
    memory = Mem()
    traces: list[ChatTrace] = []
    sent: list[list[dict]] = []

    replies = iter(
        [
            _assistant(tool_calls=[_tc("1", "search", '{"query": "A"}')]),
            _assistant(tool_calls=[_tc("2", "search", '{"query": "B"}')]),
            _assistant(content="降级交付的答案。\nUSED: [id:A1]"),  # 收尾轮
        ]
    )

    def llm(messages, tools):
        sent.append(list(messages))
        return next(replies)

    agent = MemoryAgent(memory, llm, system_prompt="S", max_turns=2,
                        context_budget=100_000, token_counter=len,
                        on_trace=traces.append)
    assert agent.chat("问") == "降级交付的答案。"
    assert len(sent) == 3  # max_turns=2 + 收尾轮 1 次（有界）
    assert "收尾轮" in sent[2][0]["content"]
    assert traces[0].termination == "finalized"
    assert traces[0].used_refs == ["[id:A1]"]


def test_finalize_turn_still_toolcall_falls_back_forced():
    """收尾轮仍返回纯工具调用（无内容）→ 保持 forced 兜底文本，不再继续调用。"""
    memory = Mem()
    traces: list[ChatTrace] = []

    def llm(m, t):
        return _assistant(tool_calls=[_tc("x", "search", '{"query": "q"}')])

    agent = _agent(memory, llm, on_trace=traces.append)
    assert "最大轮次" in agent.chat("问")
    assert traces[0].termination == "forced"


def test_forced_no_finalize_when_budget_off():
    """默认关闭：无收尾轮（LLM 恰好调 max_turns 次），行为与现状一致。"""
    memory = Mem()
    traces: list[ChatTrace] = []
    calls = {"n": 0}

    def llm(m, t):
        calls["n"] += 1
        return _assistant(tool_calls=[_tc("x", "search", '{"query": "q"}')])

    agent = MemoryAgent(memory, llm, max_turns=3, on_trace=traces.append)
    assert "最大轮次" in agent.chat("问")
    assert calls["n"] == 3  # 无 +1 收尾轮
    assert traces[0].termination == "forced"

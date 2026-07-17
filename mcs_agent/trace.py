"""LLM 调用链路追踪数据结构。

轻量追踪模块，记录每次 LLM 调用和工具调用的完整生命周期，
聚合为 ``ChatTrace`` 通过回调暴露给调用方。

零外部依赖（dataclasses + time 均为标准库）。
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class TokenUsage:
    """单次 LLM 调用的 token 用量。

    各字段均可 None（OpenAI 兼容后端可能不返回 usage）。
    """

    prompt_tokens: int | None = None
    completion_tokens: int | None = None
    total_tokens: int | None = None


@dataclass
class MessageSummary:
    """消息摘要：role + content 前 100 字符。"""

    role: str
    content_preview: str


@dataclass
class LLMCallTrace:
    """单次 LLM 调用追踪。

    由 ``make_openai_llm_call`` 返回的 callable 内部构造，
    附加到返回 dict 的 ``_trace`` 键。
    """

    model: str
    latency_ms: float
    token_usage: TokenUsage | None
    timestamp: float
    request_summary: list[MessageSummary]
    response_summary: str
    tool_call_names: list[str]


@dataclass
class ToolCallTrace:
    """单次工具调用追踪。

    由 ``MemoryAgent._dispatch()`` 返回。
    """

    tool_name: str
    args_summary: str
    result_summary: str
    latency_ms: float
    error: str | None


@dataclass
class ContextEvent:
    """一次会话上下文管理事件（change agent-context-autonomy）。

    ``kind`` 取值：``fold``（工具结果首次折叠为存根）/ ``evict``（逐出为墓碑）/
    ``pin`` / ``unpin`` / ``pin_rejected``（超防御上限）/ ``reject``（预算耗尽拒绝
    注入新工具结果）/ ``overflow``（折叠+逐出后仍超预算，降级发送）/
    ``dup_call``（同参重复调用，detail 含 pin 集是否变化——盲目重复率数据源）。
    ``tokens_before`` / ``tokens_after`` 仅 fold 事件填写（折叠前后 token）。
    """

    kind: str
    stub_no: int | None = None
    detail: str = ""
    tokens_before: int | None = None
    tokens_after: int | None = None


@dataclass
class ChatTrace:
    """一次完整 chat 链路追踪。

    聚合该次对话的所有 LLM 调用和工具调用记录，
    ``total_tokens`` 为所有 LLM 调用的 token 总和（任一缺失时为 None，
    无 LLM 调用记录时也为 None——"无记录"不等于"0 token"）。
    """

    user_message: str
    reply: str
    llm_calls: list[LLMCallTrace] = field(default_factory=list)
    tool_calls: list[ToolCallTrace] = field(default_factory=list)
    total_latency_ms: float = 0.0
    # agent-context-autonomy：上下文管理事件与终止类型。
    # termination：finish（FINISH 显式收束）/ implicit（无标记无工具调用）/
    # finalized（轮次耗尽后收尾轮交付答案）/ forced（超 max_turns 且收尾轮也无内容）/
    # error（LLM 调用失败）；预算关闭时无 FINISH 解析、无收尾轮，正常收尾均记 implicit。
    # used_refs 为 FINISH / 收尾轮的 USED: 引用（存根编号 / 节点 id）。
    context_events: list[ContextEvent] = field(default_factory=list)
    termination: str = "implicit"
    used_refs: list[str] = field(default_factory=list)
    total_tokens: int | None = field(default=None, init=False)

    def __post_init__(self) -> None:
        self._compute_total_tokens()

    def _compute_total_tokens(self) -> None:
        """计算所有 LLM 调用的 token 总和。

        任一 ``LLMCallTrace.token_usage`` 为 None 或其 ``total_tokens`` 为 None
        时，整体为 None。``llm_calls`` 为空时也为 None（无法确定 token 用量）。
        """
        if not self.llm_calls:
            self.total_tokens = None
            return
        total = 0
        for trace in self.llm_calls:
            if trace.token_usage is None or trace.token_usage.total_tokens is None:
                self.total_tokens = None
                return
            total += trace.token_usage.total_tokens
        self.total_tokens = total

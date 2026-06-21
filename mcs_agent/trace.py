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

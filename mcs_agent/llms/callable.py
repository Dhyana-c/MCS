"""``CallableAgentLLM``：裸 callable -> ``AgentLLMInterface`` 适配器。

包旧口径 ``llm_call(messages, tools) -> dict`` callable，桥接到新 ABC。兼容旧实现
往返回 dict 偷塞 ``_trace`` 键的做法——本适配器把它提到 ``AssistantMessage.trace``。
**适配发生在 ``MemoryAgent.__init__``**（传入 callable 自动包），保既有注入式测试
零改动（见 design D8）。
"""

from __future__ import annotations

from typing import Callable

from mcs_agent.llms.base import AgentLLMInterface, AssistantMessage
from mcs_agent.trace import LLMCallTrace


class CallableAgentLLM(AgentLLMInterface):
    """包裸 callable，对外暴露 ``AgentLLMInterface``。"""

    def __init__(
        self, llm_call: Callable[[list[dict], list[dict]], dict]
    ) -> None:
        self._llm_call = llm_call

    def chat(self, messages: list[dict], tools: list[dict]) -> AssistantMessage:
        raw = self._llm_call(messages, tools)
        if not isinstance(raw, dict):
            raise TypeError(
                f"CallableAgentLLM 包的 callable 须返回 dict， got {type(raw).__name__}"
            )
        trace = raw.get("_trace")
        return AssistantMessage(
            content=raw.get("content"),
            tool_calls=list(raw.get("tool_calls") or []),
            trace=trace if isinstance(trace, LLMCallTrace) else None,
        )

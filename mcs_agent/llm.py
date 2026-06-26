"""已废弃别名：``make_openai_llm_call``。

逻辑已搬入 ``mcs_agent.llms.openai.OpenAIAgentLLM``（见 change memory-agent-builder
design D8）。本函数保留为薄别名，返回旧口径 ``llm_call(messages, tools) -> dict``
（回填 ``_trace`` 键，保持旧 callable 形状），供仍 import 它的代码过渡、避免 import
断裂。与 ``MEMORY_TOOLS`` 废弃别名对称；后续 change 移除。
"""

from __future__ import annotations

from typing import Callable

from mcs_agent.llms.openai import OpenAIAgentLLM

__all__ = ["make_openai_llm_call"]


def make_openai_llm_call(
    model: str,
    api_key: str,
    base_url: str | None = None,
) -> Callable[[list[dict], list[dict]], dict]:
    """[已废弃] 构造 ``llm_call(messages, tools) -> assistant_message_dict`` callable。

    内部委托 ``OpenAIAgentLLM``，回填 ``_trace`` 键以保持旧 dict 口径。
    改用 ``mcs_agent.llms.OpenAIAgentLLM``。
    """
    backend = OpenAIAgentLLM(model, api_key, base_url)

    def llm_call(messages: list[dict], tools: list[dict]) -> dict:
        msg = backend.chat(messages, tools)
        return {
            "role": "assistant",
            "content": msg.content,
            "tool_calls": msg.tool_calls,
            "_trace": msg.trace,
        }

    return llm_call

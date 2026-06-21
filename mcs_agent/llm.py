"""生产用 LLM 调用：openai SDK（兼容 DeepSeek 等 openai 兼容后端）。

把 openai 客户端包成 ``loop.py`` 期望的 ``llm_call(messages, tools) -> dict`` 接口。
``openai`` 在函数内惰性 import，与 loop/memory 解耦（测试不需真实客户端）。

返回的 dict 新增 ``_trace`` 键（``LLMCallTrace``），供 loop.py 提取追踪数据；
追加到 messages 前必须剥离此键。
"""

from __future__ import annotations

import time
from typing import Callable

from mcs_agent.trace import LLMCallTrace, MessageSummary, TokenUsage

__all__ = ["make_openai_llm_call"]


def make_openai_llm_call(
    model: str,
    api_key: str,
    base_url: str | None = None,
) -> Callable[[list[dict], list[dict]], dict]:
    """构造 ``llm_call(messages, tools) -> assistant_message_dict`` 的 callable。

    Args:
        model: 模型名（如 ``deepseek-chat``）。
        api_key: API 密钥。
        base_url: openai 兼容端点；DeepSeek 用 ``https://api.deepseek.com``，
            官方 openai 留 None。
    """
    from openai import OpenAI

    client = OpenAI(api_key=api_key, base_url=base_url)

    def llm_call(messages: list[dict], tools: list[dict]) -> dict:
        wall_time = time.time()
        t0 = time.perf_counter()
        resp = client.chat.completions.create(
            model=model, messages=messages, tools=tools
        )
        latency_ms = (time.perf_counter() - t0) * 1000
        assistant = resp.choices[0].message.model_dump()

        # 提取 token 用量
        usage = resp.usage
        token_usage: TokenUsage | None = None
        if usage is not None:
            token_usage = TokenUsage(
                prompt_tokens=usage.prompt_tokens,
                completion_tokens=usage.completion_tokens,
                total_tokens=usage.total_tokens,
            )

        # 构造 request_summary
        # NOTE: content 假设为 str；OpenAI 多模态 content 是 list，将来引入需适配
        request_summary: list[MessageSummary] = []
        for msg in messages:
            content = msg.get("content") or ""
            request_summary.append(
                MessageSummary(
                    role=msg.get("role", ""),
                    content_preview=content[:100],
                )
            )

        # 构造 response_summary
        resp_content = assistant.get("content") or ""
        response_summary = resp_content[:200]

        # 提取 tool_call_names
        tool_call_names: list[str] = []
        for tc in assistant.get("tool_calls") or []:
            fn = tc.get("function", {})
            if fn.get("name"):
                tool_call_names.append(fn["name"])

        trace = LLMCallTrace(
            model=model,
            latency_ms=latency_ms,
            token_usage=token_usage,
            timestamp=wall_time,
            request_summary=request_summary,
            response_summary=response_summary,
            tool_call_names=tool_call_names,
        )
        assistant["_trace"] = trace
        return assistant

    return llm_call

"""OpenAI 兼容后端（覆盖 deepseek / ollama / 任意 openai 兼容端点）。

把现 ``make_openai_llm_call`` 的逻辑搬进 ``OpenAIAgentLLM`` 类；trace 走
``AssistantMessage.trace`` 一等字段（不再塞 dict ``_trace`` 键）。``openai`` SDK
在 ``chat()`` 内惰性 import，与 base / registry 解耦（测试 / 未装后端不破）。
"""

from __future__ import annotations

import time

from mcs_agent.llms.base import AgentLLMInterface, AssistantMessage
from mcs_agent.trace import LLMCallTrace, MessageSummary, TokenUsage


class OpenAIAgentLLM(AgentLLMInterface):
    """openai chat-completions 协议的 agent LLM 后端。

    Args:
        model: 模型名（如 ``deepseek-chat``）。
        api_key: API 密钥。
        base_url: openai 兼容端点；DeepSeek 用 ``https://api.deepseek.com``、
            ollama 用 ``http://localhost:11434/v1``、官方 openai 留 None。
        auth_token: 仅 claude 有意义（Bearer）；openai-compat 后端忽略。
    """

    def __init__(
        self,
        model: str,
        api_key: str,
        base_url: str | None = None,
        auth_token: str | None = None,  # noqa: ARG002  # openai-compat 忽略；仅 claude 用
    ) -> None:
        self.model = model
        self.api_key = api_key
        self.base_url = base_url
        self._client = None  # 惰性构造后缓存（避免每次 chat 重建 httpx 连接池）

    def _get_client(self):  # type: ignore[no-untyped-def]
        """惰性 import + 构造并缓存 openai client（未装 SDK 不影响本类构造）。"""
        if self._client is None:
            from openai import OpenAI  # 惰性 import

            self._client = OpenAI(api_key=self.api_key, base_url=self.base_url)
        return self._client

    def chat(self, messages: list[dict], tools: list[dict]) -> AssistantMessage:
        client = self._get_client()
        wall_time = time.time()
        t0 = time.perf_counter()
        resp = client.chat.completions.create(
            model=self.model, messages=messages, tools=tools
        )
        latency_ms = (time.perf_counter() - t0) * 1000

        # model_dump 保完整 tool_calls 结构（id / type / function），供多轮回放
        assistant = resp.choices[0].message.model_dump()
        content = assistant.get("content")
        tool_calls = assistant.get("tool_calls") or []

        # === trace（与旧 make_openai_llm_call 同口径） ===
        usage = resp.usage
        token_usage: TokenUsage | None = None
        if usage is not None:
            token_usage = TokenUsage(
                prompt_tokens=usage.prompt_tokens,
                completion_tokens=usage.completion_tokens,
                total_tokens=usage.total_tokens,
            )

        # NOTE: content 假设为 str | None；OpenAI 多模态 content 是 list，将来引入需适配
        request_summary: list[MessageSummary] = [
            MessageSummary(role=m.get("role", ""), content_preview=(m.get("content") or "")[:100])
            for m in messages
        ]
        response_summary = (content or "")[:200]

        tool_call_names: list[str] = []
        for tc in tool_calls:
            fn = tc.get("function", {})
            if fn.get("name"):
                tool_call_names.append(fn["name"])

        trace = LLMCallTrace(
            model=self.model,
            latency_ms=latency_ms,
            token_usage=token_usage,
            timestamp=wall_time,
            request_summary=request_summary,
            response_summary=response_summary,
            tool_call_names=tool_call_names,
        )
        return AssistantMessage(content=content, tool_calls=tool_calls, trace=trace)

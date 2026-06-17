"""生产用 LLM 调用：openai SDK（兼容 DeepSeek 等 openai 兼容后端）。

把 openai 客户端包成 ``loop.py`` 期望的 ``llm_call(messages, tools) -> dict`` 接口。
``openai`` 在函数内惰性 import，与 loop/memory 解耦（测试不需真实客户端）。
"""

from __future__ import annotations

from typing import Callable

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
        resp = client.chat.completions.create(
            model=model, messages=messages, tools=tools
        )
        return resp.choices[0].message.model_dump()

    return llm_call

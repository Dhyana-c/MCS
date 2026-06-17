"""记忆 agent 的 ReAct loop。

agent 自有 LLM（独立于 MCS 的 read_llm），经 tool calling 调记忆工具
（``memory_query`` 查、``memory_ingest`` 写）。LLM 调用抽成可注入的 callable，
便于测试（注入脚本化 mock，不依赖真实 API）。

消息与工具格式遵循 openai chat completions（deepseek 等 openai 兼容后端通用）：
``llm_call(messages, tools) -> assistant_message_dict``，dict 含 ``content`` / ``tool_calls``。
"""

from __future__ import annotations

import json
import logging
from typing import Any, Callable

logger = logging.getLogger(__name__)

__all__ = ["MemoryAgent", "DEFAULT_SYSTEM_PROMPT", "MEMORY_TOOLS"]


DEFAULT_SYSTEM_PROMPT = (
    "你是一个基于个人记忆图谱的助手。你拥有以下记忆工具：\n"
    "- memory_query：在记忆图谱中查询与问题相关的内容（语义检索，可能多跳）。\n"
    "- memory_ingest：把一段信息写入记忆图谱（仅当用户明确要记住某事时使用）。\n\n"
    "回答用户问题时，先用 memory_query 检索相关记忆，再据检索结果作答；"
    "记忆不足则据实说明。除非用户明确要求记住，否则不要调用 memory_ingest。"
)


MEMORY_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "memory_query",
            "description": "在记忆图谱中查询与 query 相关的节点与关系，返回可读文本。",
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "查询内容（自然语言）",
                    }
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "memory_ingest",
            "description": "把一段文本写入记忆图谱，自动抽取概念并入图。仅在用户明确要记住时调用。",
            "parameters": {
                "type": "object",
                "properties": {
                    "text": {
                        "type": "string",
                        "description": "要记住的文本",
                    }
                },
                "required": ["text"],
            },
        },
    },
]


class MemoryAgent:
    """ReAct 记忆 agent。LLM 经 tool calling 调 MemoryStore 的 query / ingest。

    Args:
        memory: 暴露 ``query(text)`` / ``ingest(text)`` 的对象（通常是 ``MemoryStore``）。
        llm_call: ``(messages, tools) -> assistant_message_dict`` 的 callable。
        system_prompt: 系统提示词。
        max_turns: 单次 chat 的最大 LLM 轮次（防失控循环）。
    """

    def __init__(
        self,
        memory: Any,
        llm_call: Callable[[list[dict], list[dict]], dict],
        system_prompt: str = DEFAULT_SYSTEM_PROMPT,
        max_turns: int = 8,
    ) -> None:
        self.memory = memory
        self.llm_call = llm_call
        self.system_prompt = system_prompt
        self.max_turns = max_turns

    def chat(self, user_message: str) -> str:
        """跑一轮 ReAct：LLM 决定调工具或给最终答案，返回最终答复文本。"""
        messages: list[dict] = [
            {"role": "system", "content": self.system_prompt},
            {"role": "user", "content": user_message},
        ]
        for _ in range(self.max_turns):
            assistant = self.llm_call(messages, MEMORY_TOOLS)
            messages.append(assistant)
            tool_calls = assistant.get("tool_calls")
            if not tool_calls:
                return assistant.get("content") or ""
            for tool_call in tool_calls:
                result = self._dispatch(tool_call)
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.get("id", ""),
                        "content": result,
                    }
                )
        return "（达到最大轮次，未能给出最终答复。）"

    def _dispatch(self, tool_call: dict) -> str:
        """执行单个工具调用，返回结果文本（异常隔离为 [error] 文本，不抛出）。"""
        fn = tool_call.get("function", {})
        name = fn.get("name", "")
        raw_args = fn.get("arguments", "{}")
        try:
            args = (
                json.loads(raw_args) if isinstance(raw_args, str) else (raw_args or {})
            )
        except json.JSONDecodeError:
            return "[error] 工具参数不是合法 JSON"
        try:
            if name == "memory_query":
                return self.memory.query(args.get("query", ""))
            if name == "memory_ingest":
                return self.memory.ingest(args.get("text", ""))
            return f"[error] 未知工具：{name}"
        except Exception as exc:  # 单次工具异常隔离，loop 不崩
            logger.warning("tool %s failed", name, exc_info=True)
            return f"[error] {type(exc).__name__}: {exc}"

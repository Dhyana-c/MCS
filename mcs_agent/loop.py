"""记忆 agent 的 ReAct loop。

agent 自有 LLM（独立于 MCS 的 read_llm），经 tool calling 调 5 个导航工具
（learn / search / associate / reason / recall）。**导航决策权交给 LLM**：LLM
决定查什么、用哪个种子、用哪种扩展模式、选哪两个节点找路径。LLM 调用抽成
可注入的 callable，便于测试（注入脚本化 mock，不依赖真实 API）。

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
    "你是一个记忆导航 agent。你不直接背事实，而是通过工具探索记忆图作答：\n"
    "- search：搜索记忆图的入口种子。mode=keyword 按用户输入做字面匹配（主力，已实现）；"
    "mode=direct 返回顶层 hub 节点（无明确关键词时用，已实现）；mode=vector 未实现。\n"
    "- associate：从某个种子出发联想扩展（BFS）。mode=mcs 已实现（主力）；hot、random 未实现。\n"
    "- reason：在两个已知节点间找连通路径（允许失败）。\n"
    "- recall：回忆近期热点事件（未实现）。\n"
    "- learn：把一段信息写入记忆图谱（仅当用户明确要记住时用）。\n\n"
    "你决定用哪个工具、哪个种子、哪种模式、选哪两个节点。先把相关记忆探索充分，"
    "再据探索结果作答；记忆不足据实说明。工具返回的节点带 [id:...]，后续工具用它引用。"
    "未实现的模式会返回提示，请改用可用项。"
)


MEMORY_TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "learn",
            "description": (
                "把一段信息写入记忆图谱（复用 MCS 写管线，自动抽概念入图）。"
                "仅当用户明确要求记住时调用。"
            ),
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
    {
        "type": "function",
        "function": {
            "name": "search",
            "description": (
                "搜索记忆图谱的种子节点作为导航入口，返回节点列表（含 id）。"
                "mode=keyword 按用户输入做关键词/字面匹配（主力，已实现）；"
                "mode=direct 返回顶层 hub 节点（无明确关键词时用，已实现）；"
                "mode=vector 向量检索（未实现，勿用）。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "query": {
                        "type": "string",
                        "description": "查询内容（自然语言）",
                    },
                    "mode": {
                        "type": "string",
                        "enum": ["keyword", "direct", "vector"],
                        "description": "搜索模式，默认 keyword",
                    },
                },
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "associate",
            "description": (
                "从指定种子节点出发做联想扩展（BFS），返回扩展子图（含 id）。"
                "mode=mcs 用 MCS 事实 BFS（主力，已实现）；"
                "mode=hot 热点排序（未实现）；mode=random 随机截断（未实现）。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "seed_id": {
                        "type": "string",
                        "description": "种子节点 id（由 search 返回的 [id:...]）",
                    },
                    "mode": {
                        "type": "string",
                        "enum": ["mcs", "hot", "random"],
                        "description": "扩展模式，默认 mcs",
                    },
                },
                "required": ["seed_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "reason",
            "description": (
                "在两个已知节点间找连通路径（双向最短路径，允许失败）。"
                "source_id/target_id 由前序工具返回的 [id:...] 提供。找不到则告知无路径。"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "source_id": {
                        "type": "string",
                        "description": "起点节点 id",
                    },
                    "target_id": {
                        "type": "string",
                        "description": "终点节点 id",
                    },
                },
                "required": ["source_id", "target_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "recall",
            "description": "回忆近期热点事件。（未实现：依赖事件节点与热点排序，暂不可用。）",
            "parameters": {
                "type": "object",
                "properties": {
                    "limit": {
                        "type": "integer",
                        "description": "返回事件数上限，默认 5",
                    }
                },
                "required": [],
            },
        },
    },
]


class MemoryAgent:
    """ReAct 记忆 agent。LLM 经 tool calling 调 5 个导航工具探索记忆图。

    Args:
        memory: 暴露 learn/search/associate/find_path/recall 的对象（通常是 ``MemoryStore``）。
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
            if name == "learn":
                return self.memory.learn(args.get("text", ""))
            if name == "search":
                return self.memory.search(
                    args.get("query", ""), args.get("mode", "keyword")
                )
            if name == "associate":
                return self.memory.associate(
                    args.get("seed_id", ""), args.get("mode", "mcs")
                )
            if name == "reason":
                return self.memory.find_path(
                    args.get("source_id", ""), args.get("target_id", "")
                )
            if name == "recall":
                return self.memory.recall(args.get("limit", 5))
            return f"[error] 未知工具：{name}"
        except Exception as exc:  # 单次工具异常隔离，loop 不崩
            logger.warning("tool %s failed", name, exc_info=True)
            return f"[error] {type(exc).__name__}: {exc}"

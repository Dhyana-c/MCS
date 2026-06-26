"""Agent LLM 抽象：``AssistantMessage`` 返回值 + ``AgentLLMInterface`` ABC。

agent 自有 chat LLM 与 MCS 核心的 ``LLMInterface``（``(system, user) -> raw_str``，
无 tool-calling）接口形状不同、不能合一（见 design D1）。本模块定义 agent 侧
chat 后端抽象：``chat(messages, tools) -> AssistantMessage``。

内部消息 / 工具格式以 openai chat-completions 为 lingua franca（deepseek / ollama
原生兼容；anthropic-native 后端在 adapter 内双向翻译）。ABC 只标准化"返回值"。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from mcs_agent.trace import LLMCallTrace


@dataclass
class AssistantMessage:
    """LLM 单次 chat 的标准化返回（openai chat-completions 口径）。

    ``content`` / ``tool_calls`` 与 openai assistant message 同构（``tool_calls``
    每项含完整 ``id`` / ``type`` / ``function`` 结构，供多轮 tool 消息按 id 配对、
    openai 多轮回放校验通过）。``trace`` 为一等追踪字段，替代旧实现往 dict 偷塞
    ``_trace`` 键的 hack（见 design D3）。
    """

    content: str | None
    tool_calls: list[dict] = field(default_factory=list)
    trace: LLMCallTrace | None = None


class AgentLLMInterface(ABC):
    """agent chat LLM 后端抽象。

    实现类经 ``AGENT_LLM_REGISTRY`` 按 provider 键注册，由 builder 选择。
    """

    @abstractmethod
    def chat(self, messages: list[dict], tools: list[dict]) -> AssistantMessage:
        """跑一次 chat 补全，返回标准化 ``AssistantMessage``。"""

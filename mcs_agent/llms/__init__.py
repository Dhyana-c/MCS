"""Agent LLM 后端抽象与注册表（可插拔 LLM，见 design D1/D4）。"""

from mcs_agent.llms.anthropic import AnthropicAgentLLM
from mcs_agent.llms.base import AgentLLMInterface, AssistantMessage
from mcs_agent.llms.callable import CallableAgentLLM
from mcs_agent.llms.openai import OpenAIAgentLLM
from mcs_agent.llms.registry import AGENT_LLM_REGISTRY, PROVIDER_TO_MCS_LLM

__all__ = [
    "AgentLLMInterface",
    "AssistantMessage",
    "CallableAgentLLM",
    "OpenAIAgentLLM",
    "AnthropicAgentLLM",
    "AGENT_LLM_REGISTRY",
    "PROVIDER_TO_MCS_LLM",
]

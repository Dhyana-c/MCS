"""记忆 agent：基于 MCS 记忆图谱的 ReAct agent loop。

应用层自有 LLM（可插拔后端，经 ``AgentLLMInterface``），把 MCS 当记忆工具调用。用现状
底座跑通，不动关系模型；置信 / 折叠等算法层后续接入。独立顶层包 mcs_agent（与 mcs 平级），
将来分开打包。

构造见 ``AgentBuilder`` / ``create_agent`` / ``AgentConfig.from_file``（change
memory-agent-builder）。
"""

from mcs_agent.builder import AgentBuilder, AgentConfig, LLMConfig, create_agent
from mcs_agent.llm import make_openai_llm_call
from mcs_agent.llms import (
    AGENT_LLM_REGISTRY,
    PROVIDER_TO_MCS_LLM,
    AgentLLMInterface,
    AnthropicAgentLLM,
    AssistantMessage,
    CallableAgentLLM,
    OpenAIAgentLLM,
)
from mcs_agent.loop import DEFAULT_SYSTEM_PROMPT, MEMORY_TOOLS, MemoryAgent
from mcs_agent.memory import MemoryStore
from mcs_agent.tools import BUILTIN_TOOLS, ToolSpec, ToolsetConfig

__all__ = [
    # 构造体系（change memory-agent-builder）
    "LLMConfig",
    "AgentConfig",
    "AgentBuilder",
    "create_agent",
    # LLM 后端
    "AgentLLMInterface",
    "AGENT_LLM_REGISTRY",
    "PROVIDER_TO_MCS_LLM",
    "OpenAIAgentLLM",
    "AnthropicAgentLLM",
    "CallableAgentLLM",
    "AssistantMessage",
    # 工具
    "ToolSpec",
    "BUILTIN_TOOLS",
    "ToolsetConfig",
    # 既有
    "MemoryAgent",
    "MemoryStore",
    "DEFAULT_SYSTEM_PROMPT",
    "MEMORY_TOOLS",
    "make_openai_llm_call",  # 已废弃别名（保留 import 不断裂，见 design D8）
]

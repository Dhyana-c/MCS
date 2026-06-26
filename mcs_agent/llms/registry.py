"""Provider 键 -> agent adapter 注册表 + provider -> MCS 插件短名映射。

**统一 LLM 的落点**（见 design D4）：一份 provider/model/key 配置，经
``AGENT_LLM_REGISTRY`` 选 agent adapter、经 ``PROVIDER_TO_MCS_LLM`` 映射 MCS 插件，
两侧同源。未知名早失败（builder 选不到 adapter 即抛）。

⚠️ ``PROVIDER_TO_MCS_LLM`` 的值是 **MCS 插件短名**，**仅**作 ``create_mcs(llm=...)`` /
``knowledge_graph(write_llm=...)`` 的参数用；``plugin_configs`` 的 key 必须是完整插件名
``f"{provider}_llm"``（如 ``deepseek_llm``）——见 design D6 警告。
"""

from __future__ import annotations

from mcs_agent.llms.anthropic import AnthropicAgentLLM
from mcs_agent.llms.base import AgentLLMInterface
from mcs_agent.llms.openai import OpenAIAgentLLM

# provider -> agent adapter 类
AGENT_LLM_REGISTRY: dict[str, type[AgentLLMInterface]] = {
    "deepseek": OpenAIAgentLLM,    # openai 兼容；base_url 默认 https://api.deepseek.com
    "ollama": OpenAIAgentLLM,      # openai 兼容；base_url 默认 http://localhost:11434/v1
    "claude": AnthropicAgentLLM,   # anthropic 原生；整段 history openai↔anthropic 翻译
}

# provider -> MCS 插件短名（供 create_mcs(llm=...) 用；非 plugin_configs key）
PROVIDER_TO_MCS_LLM: dict[str, str] = {
    "deepseek": "deepseek",
    "ollama": "ollama",
    "claude": "claude",
}

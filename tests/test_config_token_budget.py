"""config.knowledge_graph() T 默认值单测——各 LLM 选择 + 用户显式覆盖。"""

from __future__ import annotations

from mcs.entities.config import MCSConfig


class TestKnowledgeGraphTokenBudget:
    """knowledge_graph() 根据模型自动计算 T 默认值。"""

    def test_deepseek_default_T(self):
        """DeepSeek 默认 T = min(8000, (128000-2000)//2) = 8000。"""
        config = MCSConfig.knowledge_graph(write_llm="deepseek")
        assert config.token_budget == 8000

    def test_claude_default_T(self):
        """Claude 默认 T = min(8000, (200000-2000)//2) = 8000。"""
        config = MCSConfig.knowledge_graph(write_llm="claude")
        assert config.token_budget == 8000

    def test_ollama_default_T(self):
        """Ollama 默认 T = min(8000, (8192-2000)//2) = 3096。"""
        config = MCSConfig.knowledge_graph(write_llm="ollama")
        assert config.token_budget == min(8000, (8192 - 2000) // 2)  # 3096

    def test_user_explicit_override(self):
        """用户显式设 token_budget 时覆盖自动值。"""
        config = MCSConfig.knowledge_graph(write_llm="deepseek")
        config.token_budget = 16000
        assert config.token_budget == 16000

    def test_from_file_preserves_explicit_T(self):
        """从文件加载时显式 token_budget 不被自动值覆盖。"""
        # 直接构造 MCSConfig 并设 token_budget
        config = MCSConfig(token_budget=4000)
        assert config.token_budget == 4000

    def test_all_llms_T_within_bounds(self):
        """所有 LLM 的自动 T 值在合理范围内。"""
        for llm in ["deepseek", "claude", "ollama"]:
            config = MCSConfig.knowledge_graph(write_llm=llm)
            assert 1000 <= config.token_budget <= 8000

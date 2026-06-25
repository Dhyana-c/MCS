"""Builder 行为测试——验证 build() 把 write_llm.count_tokens 注入 TokenBudget。

早期版本用 ``inspect.getsource`` 做源码字符串断言（脆弱、不验证行为），已替换为
真正调用 ``build()`` 并断言产出的 TokenBudget 行为。
"""

from __future__ import annotations

from mcs.core.builder import MCSBuilder
from mcs.entities.config import MCSConfig


class _TestBuilder(MCSBuilder):
    """测试用 Builder——只注册 deepseek_llm，其余插件名返回 None（跳过）。"""

    def get_plugin_class(self, name):
        from mcs.plugins.llm.deepseek_llm import DeepSeekLLMPlugin

        return DeepSeekLLMPlugin if name == "deepseek_llm" else None


class TestBuilderTokenBudgetCounter:
    """build() 真正把 write_llm.count_tokens 注入 TokenBudget。"""

    @staticmethod
    def _build():
        config = MCSConfig.knowledge_graph(write_llm="deepseek")
        # 用 in-memory store，避免落盘与 schema 初始化副作用
        config.plugin_configs["sqlite_storage"]["path"] = ":memory:"
        return _TestBuilder(config).build()

    def test_build_injects_counter(self):
        """build() 产出的 TokenBudget 注入了 counter（不再为 None）。"""
        mcs = self._build()
        assert mcs.write_pipeline.token_budget._counter is not None

    def test_injected_counter_is_write_llm_tiktoken(self):
        """注入的 counter 行为 == DeepSeek 的 tiktoken 计数（证明来自 write_llm）。"""
        import tiktoken

        from mcs.core.token_budget import TokenBudget

        mcs = self._build()
        tb = mcs.write_pipeline.token_budget
        enc = tiktoken.get_encoding("cl100k_base")
        text = "深度学习是机器学习的一个子领域"

        # 走 write_llm（DeepSeek）的 tiktoken counter
        assert tb.estimate(text) == len(enc.encode(text))
        # 与无 counter 的保守校准式不同（证明 counter 确实接管了估算）
        assert tb.estimate(text) != TokenBudget(8000).estimate(text)

    def test_write_and_read_share_same_token_budget(self):
        """write_pipeline 与 query_engine 共用同一 TokenBudget（全域单一口径）。"""
        mcs = self._build()
        assert mcs.write_pipeline.token_budget is mcs.query_engine.token_budget

    def test_counter_bound_to_write_llm(self):
        """counter 是 write_llm 实例的 bound method（DeepSeekLLMPlugin.count_tokens）。"""
        mcs = self._build()
        counter = mcs.write_pipeline.token_budget._counter
        # bound method 的 __self__ 即 write_llm 实例
        assert type(counter.__self__).__name__ == "DeepSeekLLMPlugin"
        assert counter.__func__.__name__ == "count_tokens"

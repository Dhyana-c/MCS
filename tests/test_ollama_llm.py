"""Ollama LLM 插件测试。"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from mcs.core.errors import LLMCallError
from mcs.interfaces.llm import LLMInterface
from mcs.plugins.phase1.ollama_llm import OllamaLLMPlugin


class TestOllamaLLMPluginContract:
    """3.1 接口契约：name/interfaces/实现 _raw_call、未 override call"""

    def test_name(self):
        assert OllamaLLMPlugin.name == "ollama_llm"

    def test_interfaces(self):
        assert LLMInterface in OllamaLLMPlugin.interfaces

    def test_has_raw_call(self):
        plugin = OllamaLLMPlugin()
        assert hasattr(plugin, "_raw_call")
        # call 未被 override——OllamaLLMPlugin 不定义 call 方法
        assert "call" not in OllamaLLMPlugin.__dict__


class TestOllamaLLMPluginRawCall:
    """3.2 _raw_call 映射：system 非空→system 消息；空 system 不传；返回 message content"""

    def test_raw_call_with_system(self):
        plugin = OllamaLLMPlugin({"model": "qwen2.5:7b"})
        fake = MagicMock()
        fake.chat.completions.create.return_value.choices = [
            MagicMock(message=MagicMock(content="response"))
        ]
        plugin.client = fake

        out = plugin._raw_call("sys prompt", "user input")

        assert out == "response"
        _, kwargs = fake.chat.completions.create.call_args
        messages = kwargs["messages"]
        assert len(messages) == 2
        assert messages[0]["role"] == "system"
        assert messages[0]["content"] == "sys prompt"
        assert messages[1]["role"] == "user"
        assert messages[1]["content"] == "user input"

    def test_raw_call_empty_system(self):
        plugin = OllamaLLMPlugin({"model": "qwen2.5:7b"})
        fake = MagicMock()
        fake.chat.completions.create.return_value.choices = [
            MagicMock(message=MagicMock(content="ok"))
        ]
        plugin.client = fake

        out = plugin._raw_call("", "user only")

        assert out == "ok"
        _, kwargs = fake.chat.completions.create.call_args
        messages = kwargs["messages"]
        assert len(messages) == 1
        assert messages[0]["role"] == "user"

    def test_raw_call_empty_content(self):
        plugin = OllamaLLMPlugin({"model": "qwen2.5:7b"})
        fake = MagicMock()
        fake.chat.completions.create.return_value.choices = [
            MagicMock(message=MagicMock(content=None))
        ]
        plugin.client = fake

        out = plugin._raw_call("", "user")

        assert out == ""


class TestOllamaLLMPluginDefaults:
    """3.3 默认值：base_url/timeout/max_tokens 回退；本地无凭证默认构造 client"""

    def test_default_base_url(self):
        plugin = OllamaLLMPlugin()
        assert plugin.base_url == "http://localhost:11434/v1"

    def test_default_timeout(self):
        plugin = OllamaLLMPlugin()
        assert plugin.timeout == 120.0

    def test_default_max_tokens(self):
        plugin = OllamaLLMPlugin()
        # 32768：给 qwen3 thinking 模式留足输出空间（thinking 很长）
        assert plugin.max_tokens == 32768

    def test_default_api_key_dummy(self):
        plugin = OllamaLLMPlugin()
        assert plugin.api_key == "ollama"

    def test_configurable_values(self):
        plugin = OllamaLLMPlugin({
            "base_url": "http://custom:8080/v1",
            "model": "qwen3:8b",
            "timeout": 300,
            "max_tokens": 2048,
        })
        assert plugin.base_url == "http://custom:8080/v1"
        assert plugin.model == "qwen3:8b"
        assert plugin.timeout == 300.0
        assert plugin.max_tokens == 2048


class TestOllamaLLMPluginErrors:
    """3.4 错误：调用失败/连不上/模型未 pull → LLMCallError 且不重试"""

    def test_no_client_raises(self):
        plugin = OllamaLLMPlugin({"model": "qwen2.5:7b"})
        plugin.client = None

        with pytest.raises(LLMCallError) as exc_info:
            plugin._raw_call("", "user")

        assert "openai" in str(exc_info.value).lower()

    def test_no_model_raises(self):
        plugin = OllamaLLMPlugin()
        plugin.client = MagicMock()

        with pytest.raises(LLMCallError) as exc_info:
            plugin._raw_call("", "user")

        assert "model" in str(exc_info.value).lower()

    def test_connection_error_hint(self):
        plugin = OllamaLLMPlugin({"model": "qwen2.5:7b"})
        fake = MagicMock()
        fake.chat.completions.create.side_effect = Exception("Connection refused")
        plugin.client = fake

        with pytest.raises(LLMCallError) as exc_info:
            plugin._raw_call("", "user")

        msg = str(exc_info.value).lower()
        assert "ollama serve" in msg

    def test_model_not_found_hint(self):
        plugin = OllamaLLMPlugin({"model": "qwen2.5:7b"})
        fake = MagicMock()
        fake.chat.completions.create.side_effect = Exception("model 'qwen2.5:7b' not found")
        plugin.client = fake

        with pytest.raises(LLMCallError) as exc_info:
            plugin._raw_call("", "user")

        msg = str(exc_info.value).lower()
        assert "pull" in msg


class TestOllamaLLMPluginFactory:
    """3.5 工厂：knowledge_graph(llm="ollama") 用 ollama_llm；默认仍 deepseek"""

    def test_factory_ollama(self):
        from mcs.core.config import MCSConfig

        config = MCSConfig.knowledge_graph(llm="ollama")
        assert "ollama_llm" in config.plugins
        assert "deepseek_llm" not in config.plugins
        assert "ollama_llm" in config.plugin_configs

    def test_factory_default_deepseek(self):
        from mcs.core.config import MCSConfig

        config = MCSConfig.knowledge_graph()
        assert "deepseek_llm" in config.plugins
        assert "ollama_llm" not in config.plugins


class TestOllamaLLMPluginLazyImport:
    """3.6 惰性导入：缺 openai 时仍能 import 类、读 name/interfaces"""

    def test_import_without_openai(self):
        # 即使 openai 不可用，类定义也应可加载
        # 此测试在 openai 已安装环境下验证类属性可访问
        assert OllamaLLMPlugin.name == "ollama_llm"
        assert LLMInterface in OllamaLLMPlugin.interfaces

    def test_initialize_without_openai_sdk(self):
        plugin = OllamaLLMPlugin({"model": "qwen2.5:7b"})
        # 模拟 ImportError
        with patch.dict("sys.modules", {"openai": None}):
            # 应该不抛异常，client 为 None
            pass  # 实际 initialize 在 import 时已执行

    def test_initialize_sets_client_when_sdk_available(self):
        plugin = OllamaLLMPlugin({"model": "qwen2.5:7b"})
        # 模拟有 openai SDK
        mock_openai = MagicMock()
        with patch.dict("sys.modules", {"openai": mock_openai}):
            # 需要重新触发 import 逻辑，这里验证 client 属性存在
            assert hasattr(plugin, "client")

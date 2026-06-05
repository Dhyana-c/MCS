"""Ollama LLM 插件测试。

后端走 Ollama 原生 ``/api/chat`` 端点（httpx），因此这里 mock 的是
``plugin.client.post`` 返回的 httpx.Response 形态，而非 OpenAI SDK。
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from mcs.core.errors import LLMCallError
from mcs.interfaces.llm import LLMInterface
from mcs.plugins.phase1.ollama_llm import OllamaLLMPlugin


def _fake_response(content="", status=200, text="", thinking=None):
    """构造一个仿 httpx.Response：暴露 status_code / text / json()。"""
    resp = MagicMock()
    resp.status_code = status
    resp.text = text
    message: dict = {}
    if content is not None:
        message["content"] = content
    if thinking is not None:
        message["thinking"] = thinking
    resp.json.return_value = {"message": message}
    return resp


def _plugin_with_post(content="", status=200, text="", thinking=None, config=None):
    """返回 (plugin, fake_client)，其中 client.post 返回构造好的响应。"""
    plugin = OllamaLLMPlugin(config or {"model": "qwen3.5:9b"})
    fake = MagicMock()
    fake.post.return_value = _fake_response(content, status, text, thinking)
    plugin.client = fake
    return plugin, fake


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
    """3.2 _raw_call 映射：原生 /api/chat 请求体；返回 message.content"""

    def test_raw_call_with_system(self):
        plugin, fake = _plugin_with_post(content="response")

        out = plugin._raw_call("sys prompt", "user input")

        assert out == "response"
        _, kwargs = fake.post.call_args
        payload = kwargs["json"]
        messages = payload["messages"]
        assert len(messages) == 2
        assert messages[0] == {"role": "system", "content": "sys prompt"}
        assert messages[1] == {"role": "user", "content": "user input"}
        # 默认关闭 thinking、非流式，options 透传 num_predict/num_ctx
        assert payload["think"] is False
        assert payload["stream"] is False
        assert payload["options"]["num_predict"] == plugin.max_tokens
        assert payload["options"]["num_ctx"] == plugin.num_ctx

    def test_raw_call_empty_system(self):
        plugin, fake = _plugin_with_post(content="ok")

        out = plugin._raw_call("", "user only")

        assert out == "ok"
        messages = fake.post.call_args.kwargs["json"]["messages"]
        assert len(messages) == 1
        assert messages[0]["role"] == "user"

    def test_raw_call_empty_content(self):
        plugin, _ = _plugin_with_post(content=None)

        out = plugin._raw_call("", "user")

        assert out == ""

    def test_raw_call_posts_to_native_chat_endpoint(self):
        plugin, fake = _plugin_with_post(
            content="x", config={"model": "m", "base_url": "http://h:11434/v1"}
        )

        plugin._raw_call("", "u")

        # chat_url 作为第一个位置参数传给 client.post
        assert fake.post.call_args[0][0] == "http://h:11434/api/chat"

    def test_raw_call_extracts_json_from_thinking_when_content_empty(self):
        # content 空但 thinking 末尾带 JSON 围栏 → 兜底提取
        plugin, _ = _plugin_with_post(
            content="", thinking='思考过程…\n```json\n["A", "B"]\n```'
        )

        out = plugin._raw_call("", "user")

        assert out == '["A", "B"]'

    def test_think_flag_propagates(self):
        plugin, fake = _plugin_with_post(
            content="x", config={"model": "m", "think": True}
        )

        plugin._raw_call("", "u")

        assert fake.post.call_args.kwargs["json"]["think"] is True


class TestOllamaLLMPluginDefaults:
    """3.3 默认值：base_url/timeout/max_tokens/num_ctx/think 回退"""

    def test_default_base_url(self):
        assert OllamaLLMPlugin().base_url == "http://localhost:11434/v1"

    def test_default_timeout(self):
        assert OllamaLLMPlugin().timeout == 120.0

    def test_default_max_tokens(self):
        # 32768：给思维模型/长输出留足 num_predict 空间
        assert OllamaLLMPlugin().max_tokens == 32768

    def test_default_num_ctx(self):
        # 8192：避免长文档块被 Ollama 默认上下文窗口静默截断
        assert OllamaLLMPlugin().num_ctx == 8192

    def test_default_think_off(self):
        # 思维模型默认关闭 thinking（结构化 JSON 不需要 chain-of-thought）
        assert OllamaLLMPlugin().think is False

    def test_default_api_key_dummy(self):
        assert OllamaLLMPlugin().api_key == "ollama"

    def test_configurable_values(self):
        plugin = OllamaLLMPlugin({
            "base_url": "http://custom:8080/v1",
            "model": "qwen3:8b",
            "timeout": 300,
            "max_tokens": 2048,
            "num_ctx": 16384,
            "think": True,
        })
        assert plugin.base_url == "http://custom:8080/v1"
        assert plugin.model == "qwen3:8b"
        assert plugin.timeout == 300.0
        assert plugin.max_tokens == 2048
        assert plugin.num_ctx == 16384
        assert plugin.think is True


class TestOllamaLLMPluginStripThinking:
    """_strip_thinking_tags：成对标签 + 仅闭合标签的残留都应剥离。"""

    def test_paired_tags(self):
        out = OllamaLLMPlugin._strip_thinking_tags("<think>推理过程</think>\n\n答案")
        assert out == "答案"

    def test_stray_closing_tag_only(self):
        # think=False 下模型偶尔输出无开标签的前导思考 + </think>
        out = OllamaLLMPlugin._strip_thinking_tags("一些思考\n</think>\n\n真正答案")
        assert out == "真正答案"

    def test_clean_content_untouched(self):
        assert OllamaLLMPlugin._strip_thinking_tags("干净的答案") == "干净的答案"


class TestOllamaLLMPluginChatUrl:
    """chat_url 推导：归一末尾 /v1 → /api/chat"""

    def test_strips_v1_suffix(self):
        p = OllamaLLMPlugin({"base_url": "http://192.168.31.134:11434/v1"})
        assert p.chat_url == "http://192.168.31.134:11434/api/chat"

    def test_without_v1(self):
        p = OllamaLLMPlugin({"base_url": "http://localhost:11434"})
        assert p.chat_url == "http://localhost:11434/api/chat"

    def test_trailing_slash(self):
        p = OllamaLLMPlugin({"base_url": "http://localhost:11434/v1/"})
        assert p.chat_url == "http://localhost:11434/api/chat"


class TestOllamaLLMPluginErrors:
    """3.4 错误：调用失败/连不上/模型未 pull → LLMCallError 且不重试"""

    def test_no_client_raises(self):
        plugin = OllamaLLMPlugin({"model": "qwen3.5:9b"})
        plugin.client = None

        with pytest.raises(LLMCallError) as exc_info:
            plugin._raw_call("", "user")

        assert "httpx" in str(exc_info.value).lower()

    def test_no_model_raises(self):
        plugin = OllamaLLMPlugin()
        plugin.client = MagicMock()

        with pytest.raises(LLMCallError) as exc_info:
            plugin._raw_call("", "user")

        assert "model" in str(exc_info.value).lower()

    def test_connection_error_hint(self):
        plugin = OllamaLLMPlugin({"model": "qwen3.5:9b"})
        fake = MagicMock()
        fake.post.side_effect = Exception("Connection refused")
        plugin.client = fake

        with pytest.raises(LLMCallError) as exc_info:
            plugin._raw_call("", "user")

        assert "ollama serve" in str(exc_info.value).lower()

    def test_model_not_found_hint(self):
        plugin, _ = _plugin_with_post(
            status=404, text="model 'qwen3.5:9b' not found"
        )

        with pytest.raises(LLMCallError) as exc_info:
            plugin._raw_call("", "user")

        assert "pull" in str(exc_info.value).lower()


class TestOllamaLLMPluginFactory:
    """3.5 工厂：knowledge_graph(llm="ollama") 用 ollama_llm；默认仍 deepseek"""

    def test_factory_ollama(self):
        from mcs.core.config import MCSConfig

        config = MCSConfig.knowledge_graph(llm="ollama")
        assert "ollama_llm" in config.plugins
        assert "deepseek_llm" not in config.plugins
        assert "ollama_llm" in config.plugin_configs
        # 思维模型默认关闭 thinking
        assert config.plugin_configs["ollama_llm"]["think"] is False

    def test_factory_default_deepseek(self):
        from mcs.core.config import MCSConfig

        config = MCSConfig.knowledge_graph()
        assert "deepseek_llm" in config.plugins
        assert "ollama_llm" not in config.plugins


class TestOllamaLLMPluginLazyImport:
    """3.6 惰性导入：缺 httpx 时仍能 import 类、读 name/interfaces"""

    def test_import_without_sdk(self):
        # 即使 httpx 不可用，类定义也应可加载并读取类属性
        assert OllamaLLMPlugin.name == "ollama_llm"
        assert LLMInterface in OllamaLLMPlugin.interfaces

    def test_initialize_constructs_and_shutdown_closes_client(self):
        plugin = OllamaLLMPlugin({"model": "qwen3.5:9b"})
        ctx = MagicMock()  # 提供 context_renderer 给 attach_renderer
        plugin.initialize(ctx)
        assert plugin.client is not None
        plugin.shutdown()
        assert plugin.client is None

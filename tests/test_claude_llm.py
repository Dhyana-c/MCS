"""ClaudeLLMPlugin 测试：接口契约、零 prompt 模板、_raw_call 映射、错误处理。"""

from __future__ import annotations

import inspect

import pytest

from mcs.core.errors import LLMCallError
from mcs.interfaces.llm import LLMInterface
from mcs.plugins.phase1.claude_llm import ClaudeLLMPlugin

# === 接口契约 ===


def test_name_and_interfaces():
    p = ClaudeLLMPlugin({})
    assert p.get_name() == "claude_llm"
    assert p.get_type().value == "llm"


def test_does_not_override_call():
    """call 编排必须继承自基类，未被厂商插件重写。"""
    assert ClaudeLLMPlugin.call is LLMInterface.call


def test_lazy_import_class_loadable_without_credentials():
    """不配置凭证也能实例化并读取 name/type（不触发 anthropic 导入）。"""
    p = ClaudeLLMPlugin({})
    assert p.get_name() == "claude_llm"
    assert p.get_type().value == "llm"
    assert p.client is None


# === 零 prompt 模板 ===


def test_source_has_no_prompt_templates():
    import mcs.plugins.phase1.claude_llm as mod

    full = inspect.getsource(mod)
    for forbidden in ["你是", "extract", "判断", "{name}", "{content}"]:
        assert forbidden not in full, f"厂商适配器不得含 {forbidden!r}"


# === _raw_call 映射（注入 fake client） ===


class _FakeBlock:
    def __init__(self, text: str) -> None:
        self.text = text


class _FakeResp:
    def __init__(self, blocks: list) -> None:
        self.content = blocks


class _FakeMessages:
    def __init__(self, recorder: dict, resp: _FakeResp) -> None:
        self._recorder = recorder
        self._resp = resp

    def create(self, **kwargs):
        self._recorder.update(kwargs)
        return self._resp


class _FakeClient:
    def __init__(self, recorder: dict, resp: _FakeResp) -> None:
        self.messages = _FakeMessages(recorder, resp)


def _plugin_with_fake_client(blocks: list, recorder: dict) -> ClaudeLLMPlugin:
    p = ClaudeLLMPlugin({"auth_token": "x", "model": "m", "max_tokens": 256})
    p.client = _FakeClient(recorder, _FakeResp(blocks))
    return p


def test_raw_call_maps_system_and_user():
    rec: dict = {}
    p = _plugin_with_fake_client([_FakeBlock("hello")], rec)
    out = p._raw_call("SYS", "USR")
    assert out == "hello"
    assert rec["system"] == [{"type": "text", "text": "SYS"}]
    assert rec["messages"] == [{"role": "user", "content": "USR"}]
    assert rec["model"] == "m"
    assert rec["max_tokens"] == 256


def test_raw_call_omits_empty_system():
    rec: dict = {}
    p = _plugin_with_fake_client([_FakeBlock("ok")], rec)
    p._raw_call("", "USR")
    assert "system" not in rec


def test_raw_call_concatenates_text_blocks():
    rec: dict = {}
    p = _plugin_with_fake_client(
        [_FakeBlock("a"), _FakeBlock("b"), _FakeBlock("c")], rec
    )
    assert p._raw_call("s", "u") == "abc"


def test_raw_call_without_client_raises():
    p = ClaudeLLMPlugin({})
    assert p.client is None
    with pytest.raises(LLMCallError):
        p._raw_call("s", "u")


def test_raw_call_wraps_vendor_error_as_llm_call_error():
    class _BoomMessages:
        def create(self, **kwargs):
            raise RuntimeError("boom")

    class _BoomClient:
        messages = _BoomMessages()

    p = ClaudeLLMPlugin({"auth_token": "x"})
    p.client = _BoomClient()
    with pytest.raises(LLMCallError):
        p._raw_call("s", "u")


# === 注册表与默认后端 ===


def test_registry_contains_claude():
    from mcs import _default_plugin_registry

    reg = _default_plugin_registry()
    assert reg.get("claude_llm") is ClaudeLLMPlugin


def test_default_backend_stays_deepseek_claude_is_opt_in():
    from mcs import MCSConfig

    default = MCSConfig.knowledge_graph()
    assert "deepseek_llm" in default.plugins
    assert "claude_llm" not in default.plugins

    claude = MCSConfig.knowledge_graph(llm="claude")
    assert "claude_llm" in claude.plugins
    assert "deepseek_llm" not in claude.plugins
    # 等量替换：插件总数不变。
    assert len(claude.plugins) == len(default.plugins)


def test_unknown_llm_choice_raises():
    from mcs import MCSConfig

    with pytest.raises(ValueError):
        MCSConfig.knowledge_graph(llm="bogus")

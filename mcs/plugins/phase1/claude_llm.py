"""ClaudeLLMPlugin - Anthropic Claude (Messages API) LLM 后端。

实现统一的 ``LLMInterface``。厂商特定的部分仅是
``_raw_call(system, user) -> str``；其余所有内容（渲染、prompt 组装、
解析）均由 ``LLMInterface`` 的基类实现处理。

可用于官方 Anthropic 端点，也可通过 ``base_url`` 指向兼容网关
（如反代第三方模型的 Messages 协议网关）。

配置键：
  - ``auth_token`` (Bearer 授权；与 ``api_key`` 二选一，优先)
  - ``api_key``    (x-api-key 授权)
  - ``model``      (默认: ``"claude-3-5-sonnet-latest"``)
  - ``base_url``   (默认: ``"https://api.anthropic.com"``)
  - ``timeout``    (默认: 60 秒)
  - ``max_tokens`` (默认: 4096；Messages API 必填项)
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

from mcs.core.errors import LLMCallError
from mcs.interfaces.llm import LLMInterface
from mcs.plugins.base import Plugin

if TYPE_CHECKING:
    from mcs.core.plugin_manager import PluginContext


class ClaudeLLMPlugin(Plugin, LLMInterface):
    """通过 Anthropic Messages API 的 Claude LLM 后端。"""

    name: ClassVar[str] = "claude_llm"
    version: ClassVar[str] = "0.1.0"
    interfaces: ClassVar[list[type]] = [LLMInterface]

    def __init__(self, config: dict | None = None) -> None:
        super().__init__(config)
        self.auth_token: str = self.config.get("auth_token", "")
        self.api_key: str = self.config.get("api_key", "")
        self.model: str = self.config.get("model", "claude-3-5-sonnet-latest")
        self.base_url: str = self.config.get(
            "base_url", "https://api.anthropic.com"
        )
        self.timeout: float = float(self.config.get("timeout", 60.0))
        self.max_tokens: int = int(self.config.get("max_tokens", 4096))
        self.client: Any = None

    # === 插件生命周期 ===

    def initialize(self, context: PluginContext) -> None:
        # 连接框架的 ContextRenderer，以便基类 ``call`` 可以使用它。
        self.attach_renderer(context.context_renderer)
        # 仅在有凭证时才尝试构造客户端；惰性导入 anthropic，使没有它的
        # 测试环境仍能加载插件类（例如仅检查 name/interfaces 的测试）。
        if not (self.auth_token or self.api_key):
            return
        try:
            from anthropic import Anthropic  # type: ignore[import]
        except ImportError:
            self.client = None
            return
        kwargs: dict[str, Any] = {
            "base_url": self.base_url,
            "timeout": self.timeout,
        }
        # auth_token 优先（Bearer 授权）；否则回退到 api_key（x-api-key）。
        if self.auth_token:
            kwargs["auth_token"] = self.auth_token
        else:
            kwargs["api_key"] = self.api_key
        self.client = Anthropic(**kwargs)

    def shutdown(self) -> None:
        self.client = None

    # === LLMInterface ===

    def _raw_call(self, system: str, user: str) -> str:
        if self.client is None:
            raise LLMCallError(
                "Claude 客户端未初始化；请安装 ``anthropic`` 并在插件配置中"
                "设置 ``auth_token`` 或 ``api_key``（或附加模拟 LLM）。"
            )
        try:
            kwargs: dict[str, Any] = {
                "model": self.model,
                "max_tokens": self.max_tokens,
                "messages": [{"role": "user", "content": user}],
            }
            if system:
                # system 以 text-block 数组形式传递：官方 Anthropic 与兼容网关
                # 均接受，而部分网关会拒绝顶层 system 字符串形式（返回 400）。
                kwargs["system"] = [{"type": "text", "text": system}]
            resp = self.client.messages.create(**kwargs)
            return _collect_text(resp)
        except Exception as e:  # pragma: no cover - 网络错误
            raise LLMCallError(f"Claude call failed: {e}") from e


def _collect_text(resp: Any) -> str:
    """防御式提取 Messages 响应中的文本：拼接所有带 ``text`` 的内容块。

    兼容 SDK 返回的对象块（``block.text``）与网关可能返回的字典块
    （``block["text"]``）。
    """
    content = getattr(resp, "content", None)
    if content is None:
        return ""
    parts: list[str] = []
    for block in content:
        text = getattr(block, "text", None)
        if text is None and isinstance(block, dict):
            text = block.get("text")
        if text:
            parts.append(text)
    return "".join(parts)

"""DeepSeekLLMPlugin - DeepSeek LLM 后端 (OpenAI 兼容)。

实现统一的 ``LLMInterface``。厂商特定的部分仅是
``_raw_call(system, user) -> str``；其余所有内容（渲染、
提示词组装、解析）均由 ``LLMInterface`` 的基类实现处理。

配置键：
  - ``api_key``  (实际调用时必需)
  - ``model``    (默认: ``"deepseek-chat"``)
  - ``base_url`` (默认: ``"https://api.deepseek.com"``)
  - ``timeout``  (默认: 60 秒)
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

from mcs.core.errors import LLMCallError
from mcs.interfaces.llm import LLMInterface
from mcs.plugins.base import Plugin

if TYPE_CHECKING:
    from mcs.core.plugin_manager import PluginContext


class DeepSeekLLMPlugin(Plugin, LLMInterface):
    """通过 OpenAI 兼容 API 的 DeepSeek LLM 后端。"""

    name: ClassVar[str] = "deepseek_llm"
    version: ClassVar[str] = "0.1.0"
    interfaces: ClassVar[list[type]] = [LLMInterface]

    def __init__(self, config: dict | None = None) -> None:
        super().__init__(config)
        self.api_key: str = self.config.get("api_key", "")
        self.model: str = self.config.get("model", "deepseek-chat")
        self.base_url: str = self.config.get(
            "base_url", "https://api.deepseek.com"
        )
        self.timeout: float = float(self.config.get("timeout", 60.0))
        self.max_tokens: int = int(self.config.get("max_tokens", 8192))
        self.client: Any = None

    # === 插件生命周期 ===

    def initialize(self, context: PluginContext) -> None:
        # 连接框架的 ContextRenderer，以便基类 ``call`` 可以使用它。
        self.attach_renderer(context.context_renderer)
        # 延迟导入 OpenAI，以便没有它的测试环境仍能加载
        # 插件类（例如仅检查 name/interfaces 的测试）。
        if self.api_key:
            try:
                from openai import OpenAI  # type: ignore[import]

                self.client = OpenAI(
                    api_key=self.api_key,
                    base_url=self.base_url,
                    timeout=self.timeout,
                )
            except ImportError:
                self.client = None

    def shutdown(self) -> None:
        self.client = None

    # === LLMInterface ===

    def _raw_call(self, system: str, user: str) -> str:
        if self.client is None:
            raise LLMCallError(
                "DeepSeek 客户端未初始化；"
                "请在插件配置中设置 ``api_key`` 或附加模拟 LLM。"
            )
        try:
            messages = []
            if system:
                messages.append({"role": "system", "content": system})
            messages.append({"role": "user", "content": user})
            resp = self.client.chat.completions.create(
                model=self.model, messages=messages, max_tokens=self.max_tokens
            )
            return resp.choices[0].message.content or ""
        except Exception as e:  # pragma: no cover - 网络错误
            raise LLMCallError(f"DeepSeek call failed: {e}") from e

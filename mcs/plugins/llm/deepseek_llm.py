"""DeepSeekLLMPlugin - DeepSeek LLM 后端 (OpenAI 兼容)。

实现统一的 ``LLMInterface``。厂商特定的部分仅是
``_raw_call(system, user) -> str``；其余所有内容（渲染、
提示词组装、解析）均由 ``LLMInterface`` 的基类实现处理。

重试 + 退避由 ``LLMInterface._call_with_retry`` 共享机制提供，
通过 ``max_retries`` / ``base_delay`` 配置项覆盖。

配置键：
  - ``api_key``  (实际调用时必需)
  - ``model``    (默认: ``"deepseek-chat"``)
  - ``base_url`` (默认: ``"https://api.deepseek.com"``)
  - ``timeout``  (默认: 60 秒)
  - ``max_retries`` (默认: 3)
  - ``base_delay``  (默认: 1.0 秒)
  - ``thinking`` (默认: ``None``；厂商扩展参数，非 None 时透传到请求 body 顶层，
    如智谱 GLM 的 ``{"type": "disabled"}`` 关闭思维链)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from mcs.core.errors import LLMCallError
from mcs.interfaces.llm import LLMInterface

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from mcs.core.plugin_manager import PluginContext


class DeepSeekLLMPlugin(LLMInterface):
    """通过 OpenAI 兼容 API 的 DeepSeek LLM 后端。"""

    def __init__(self, config: dict | None = None) -> None:
        super().__init__(config)
        self.api_key: str = self.config.get("api_key", "")
        self.model: str = self.config.get("model", "deepseek-chat")
        self.base_url: str = self.config.get(
            "base_url", "https://api.deepseek.com"
        )
        self.timeout: float = float(self.config.get("timeout", 60.0))
        self.max_tokens: int = int(self.config.get("max_tokens", 32768))
        # 厂商扩展参数透传（如智谱 GLM 的 thinking 开关 {"type":"disabled"}）。
        # 非 None 时合并进请求 body 顶层（OpenAI SDK extra_body）。
        self.thinking: dict | None = self.config.get("thinking")
        self.client: Any = None

    # === Plugin 基类方法 ===

    def get_name(self) -> str:
        return "deepseek_llm"

    # 注：LLMInterface 已提供 get_type() 和 execute()，无需重写

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
        return self._call_with_retry(self._do_raw_call, system, user)

    def _do_raw_call(self, system: str, user: str) -> str:
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
            kwargs: dict = {
                "model": self.model,
                "messages": messages,
                "max_tokens": self.max_tokens,
            }
            # 透传厂商扩展参数到请求 body 顶层（兼容 OpenAI 协议：SDK 用
            # extra_body 合并不识别的字段，如智谱 GLM 的 thinking 开关）。
            if self.thinking:
                kwargs["extra_body"] = {"thinking": self.thinking}
            resp = self.client.chat.completions.create(**kwargs)
            return resp.choices[0].message.content or ""
        except Exception as e:
            retryable = _is_retryable_openai_error(e)
            raise LLMCallError(
                f"DeepSeek call failed: {e}", retryable=retryable
            ) from e


def _is_retryable_openai_error(exc: Exception) -> bool:
    """判断 OpenAI 兼容异常是否可重试（429 / 网络错误）。"""
    try:
        import openai  # type: ignore[import]

        if isinstance(exc, openai.RateLimitError):
            return True
        if isinstance(exc, openai.APIConnectionError):
            return True
    except ImportError:
        pass
    # 回退：按状态码 / 错误信息判断
    status = getattr(exc, "status_code", None)
    if status == 429:
        return True
    msg = str(exc).lower()
    if "connection" in msg or "timeout" in msg:
        return True
    return False

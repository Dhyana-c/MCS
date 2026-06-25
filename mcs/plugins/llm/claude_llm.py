"""ClaudeLLMPlugin - Anthropic Claude (Messages API) LLM 后端。

实现统一的 ``LLMInterface``。厂商特定的部分仅是
``_raw_call(system, user) -> str``；其余所有内容（渲染、prompt 组装、
解析）均由 ``LLMInterface`` 的基类实现处理。

重试 + 退避由 ``LLMInterface._call_with_retry`` 共享机制提供，
通过 ``max_retries`` / ``base_delay`` 配置项覆盖。

可用于官方 Anthropic 端点，也可通过 ``base_url`` 指向兼容网关
（如反代第三方模型的 Messages 协议网关）。

配置键：
  - ``auth_token`` (Bearer 授权；与 ``api_key`` 二选一，优先)
  - ``api_key``    (x-api-key 授权)
  - ``model``      (默认: ``"claude-3-5-sonnet-latest"``)
  - ``base_url``   (默认: ``"https://api.anthropic.com"``)
  - ``timeout``    (默认: 60 秒)
  - ``max_tokens`` (默认: 4096；Messages API 必填项)
  - ``max_retries`` (默认: 3)
  - ``base_delay``  (默认: 1.0 秒)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from mcs.core.errors import LLMCallError
from mcs.interfaces.llm import LLMInterface

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from mcs.core.plugin_manager import PluginContext


class ClaudeLLMPlugin(LLMInterface):
    """通过 Anthropic Messages API 的 Claude LLM 后端。"""

    # 已知模型 → 上下文窗口大小
    _CONTEXT_WINDOWS: dict[str, int] = {
        "claude-3-5-sonnet-latest": 200_000,
        "claude-3-5-sonnet-20241022": 200_000,
        "claude-3-5-sonnet-20240620": 200_000,
        "claude-3-opus-latest": 200_000,
        "claude-3-opus-20240229": 200_000,
        "claude-3-haiku-20240307": 200_000,
        "claude-3-5-haiku-latest": 200_000,
        "claude-3-5-haiku-20241022": 200_000,
    }
    _DEFAULT_CONTEXT_WINDOW = 200_000

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

    # === Plugin 基类方法 ===

    def get_name(self) -> str:
        return "claude_llm"

    # 注：LLMInterface 已提供 get_type() 和 execute()，无需重写

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
        return self._call_with_retry(self._do_raw_call, system, user)

    def _do_raw_call(self, system: str, user: str) -> str:
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
        except Exception as e:
            retryable = _is_retryable_anthropic_error(e)
            raise LLMCallError(
                f"Claude call failed: {e}", retryable=retryable
            ) from e

    # === Token 计数 ===
    #
    # 运行时不 override count_tokens：走 LLMInterface 默认实现（CalibratedEstimator
    # 按 _detect_model_family 选 claude 族系数 ×1.7/÷3）。
    #
    # 曾考虑用 Anthropic count_tokens API 作精确 counter，但作为 TokenBudget 全域
    # counter 时有两个硬伤：① 查询 bounding/trim 链逐节点 estimate_node 会产生
    # O(邻域) 次同步网络调用（延迟 + Tier1 100RPM 速率限制）；② 429/网络失败降级到
    # 校准式时，同一文本在不同调用返回不同值（API 值 ↔ ×1.7），破坏铁律一"口径一致
    # 性"——而口径一致性正是 design 为该方案给出的全部论证。
    # 故 API 仅用于 bench/calibration 离线校准；运行时用确定性本地校准式。

    @property
    def context_window_size(self) -> int:
        """返回 Claude 模型的上下文窗口 token 数。

        精确匹配已知模型；未知模型回退 ``_DEFAULT_CONTEXT_WINDOW``。当前 Claude 3.x
        全族窗口均为 200000，映射表为未来窗口不同的模型预留扩展点。
        """
        return self._CONTEXT_WINDOWS.get(self.model, self._DEFAULT_CONTEXT_WINDOW)


def _is_retryable_anthropic_error(exc: Exception) -> bool:
    """Check if an Anthropic exception is retryable (429 / network / 529 overload)."""
    try:
        import anthropic  # type: ignore[import]

        if isinstance(exc, anthropic.RateLimitError):
            return True
        if isinstance(exc, anthropic.APIConnectionError):
            return True
        if isinstance(exc, anthropic.InternalServerError):
            return True  # 529 overloading 等
    except ImportError:
        pass
    # fallback: check status code
    status = getattr(exc, "status_code", None)
    if status in (429, 503, 529):
        return True
    msg = str(exc).lower()
    if "connection" in msg or "timeout" in msg or "overloaded" in msg:
        return True
    return False


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

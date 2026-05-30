"""DeepSeekLLMPlugin - DeepSeek LLM backend (OpenAI-compatible).

Implements the unified ``LLMInterface``. The vendor-specific piece is
just ``_raw_call(system, user) -> str``; everything else (rendering,
prompt assembly, parsing) is handled by ``LLMInterface``'s base impl.

Configuration keys:
  - ``api_key``  (required for actual calls)
  - ``model``    (default: ``"deepseek-chat"``)
  - ``base_url`` (default: ``"https://api.deepseek.com"``)
  - ``timeout``  (default: 60 seconds)
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

from mcs.core.errors import LLMCallError
from mcs.interfaces.llm import LLMInterface
from mcs.plugins.base import Plugin

if TYPE_CHECKING:
    from mcs.core.plugin_manager import PluginContext


class DeepSeekLLMPlugin(Plugin, LLMInterface):
    """DeepSeek LLM backend via the OpenAI-compatible API."""

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
        self.client: Any = None

    # === Plugin lifecycle ===

    def initialize(self, context: PluginContext) -> None:
        # Connect the framework's ContextRenderer so base ``call`` can use it.
        self.attach_renderer(context.context_renderer)
        # Lazy-import OpenAI so test environments without it can still load
        # the plugin class (e.g. for tests that only check name/interfaces).
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
                "DeepSeek client not initialized; "
                "set ``api_key`` in plugin config or attach a mock LLM."
            )
        try:
            messages = []
            if system:
                messages.append({"role": "system", "content": system})
            messages.append({"role": "user", "content": user})
            resp = self.client.chat.completions.create(
                model=self.model, messages=messages
            )
            return resp.choices[0].message.content or ""
        except Exception as e:  # pragma: no cover - network errors
            raise LLMCallError(f"DeepSeek call failed: {e}") from e

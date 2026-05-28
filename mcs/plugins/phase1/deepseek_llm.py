"""DeepSeekLLMPlugin - DeepSeek LLM backend (OpenAI-compatible).

Implements ``LLMInterface``. Uses the OpenAI SDK with DeepSeek's base URL.

See architecture.md §6.5.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

from mcs.interfaces.llm import LLMInterface
from mcs.plugins.base import Plugin

if TYPE_CHECKING:
    from mcs.core.graph import Node
    from mcs.core.plugin_manager import PluginContext


class DeepSeekLLMPlugin(Plugin, LLMInterface):
    """DeepSeek LLM backend via the OpenAI-compatible API.

    Phase 1 implementation pending. See architecture.md §6.5.
    """

    name: ClassVar[str] = "deepseek_llm"
    version: ClassVar[str] = "0.1.0"
    interfaces: ClassVar[list[type]] = [LLMInterface]

    def __init__(self, config: dict | None = None) -> None:
        super().__init__(config)
        self.api_key: str = self.config.get("api_key", "")
        self.model: str = self.config.get("model", "deepseek-chat")
        self.base_url: str = self.config.get("base_url", "https://api.deepseek.com")
        self.client: Any = None

    # === Plugin lifecycle ===

    def initialize(self, context: PluginContext) -> None:
        raise NotImplementedError("Phase 1 implementation pending")

    def shutdown(self) -> None:
        raise NotImplementedError("Phase 1 implementation pending")

    # === LLMInterface ===

    def call(self, prompt: str, system: str | None = None) -> str:
        raise NotImplementedError("Phase 1 implementation pending")

    def extract_concepts(self, text: str) -> list[Any]:
        raise NotImplementedError("Phase 1 implementation pending")

    def check_exists(
        self, concept: Any, subgraph: str
    ) -> tuple[bool, Node | None]:
        raise NotImplementedError("Phase 1 implementation pending")

    def decide_hub(self, subgraph: str) -> Any:
        raise NotImplementedError("Phase 1 implementation pending")

    def decide_directions(
        self,
        query: str,
        current_node: Node,
        subgraph: str,
        accumulated: list[Node],
    ) -> list[str]:
        raise NotImplementedError("Phase 1 implementation pending")

    def synthesize(self, query: str, content: str) -> str:
        raise NotImplementedError("Phase 1 implementation pending")

    def generate_aliases(self, concept: Any) -> list[str]:
        raise NotImplementedError("Phase 1 implementation pending")

    def generate_summary(self, content: str, max_tokens: int = 100) -> str:
        raise NotImplementedError("Phase 1 implementation pending")

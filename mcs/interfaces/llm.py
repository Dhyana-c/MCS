"""LLM interface - all LLM-driven semantic operations."""

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mcs.core.graph import Node


class LLMInterface(ABC):
    """Abstract LLM backend.

    Encapsulates all semantic operations: concept extraction, existence checks,
    direction decisions, summary/alias generation, answer synthesis.
    See architecture.md §3.3.
    """

    @abstractmethod
    def call(self, prompt: str, system: str | None = None) -> str:
        """Raw LLM call."""
        pass

    @abstractmethod
    def extract_concepts(self, text: str) -> list[Any]:
        """Extract concepts from text. Returns list of Concept objects."""
        pass

    @abstractmethod
    def check_exists(
        self,
        concept: Any,
        subgraph: str,
    ) -> tuple[bool, "Node | None"]:
        """Decide whether a concept already exists in the given subgraph."""
        pass

    @abstractmethod
    def decide_hub(self, subgraph: str) -> Any:
        """Decide which node becomes the hub during community merge."""
        pass

    @abstractmethod
    def decide_directions(
        self,
        query: str,
        current_node: "Node",
        subgraph: str,
        accumulated: "list[Node]",
    ) -> list[str]:
        """Decide which neighbors to expand toward."""
        pass

    @abstractmethod
    def synthesize(self, query: str, content: str) -> str:
        """Synthesize a final answer from accumulated content."""
        pass

    @abstractmethod
    def generate_aliases(self, concept: Any) -> list[str]:
        """Generate aliases for a concept (synonyms, abbreviations, etc.)."""
        pass

    @abstractmethod
    def generate_summary(self, content: str, max_tokens: int = 100) -> str:
        """Generate a compact summary."""
        pass

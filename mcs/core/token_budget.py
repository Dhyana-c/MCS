"""Token budget - constraint on subgraph size.

Phase 1 uses a simple character-based estimate (2 chars ≈ 1 token); Phase
2 may swap in a vendor-specific tokenizer for accuracy.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcs.core.graph import Node


class TokenBudget:
    """Token budget for subgraph operations.

    The conventional setting is ``T ≈ W / 2`` where W is the LLM context
    window. Phase 1 default: 8000.
    """

    def __init__(self, max_tokens: int):
        self.T = max_tokens

    def estimate(self, text: str | None) -> int:
        """Estimate token count for ``text``.

        Heuristic: 2 chars per token. Empty / None returns 0.
        """
        if not text:
            return 0
        return max(1, len(text) // 2)

    def check_subgraph(self, nodes: list[Node]) -> bool:
        """True if the combined content of ``nodes`` fits within ``T``."""
        total = 0
        for node in nodes:
            total += self.estimate(getattr(node, "content", ""))
            if total > self.T:
                return False
        return True

    def get_budget_for_merge(self) -> int:
        """Budget for merge operations (2T = full window)."""
        return self.T * 2

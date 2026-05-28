"""Token budget - constraint on subgraph size.

See architecture.md §2.2.
"""

from __future__ import annotations


class TokenBudget:
    """Token budget for subgraph operations.

    Phase 1 implementation pending. See architecture.md §2.2.
    """

    def __init__(self, max_tokens: int):
        self.T = max_tokens  # T ≈ W / 2

    def estimate(self, text: str) -> int:
        """Estimate token count for text."""
        raise NotImplementedError("Phase 1 implementation pending")

    def check_subgraph(self, nodes: list) -> bool:
        """Check whether a list of nodes fits within budget."""
        raise NotImplementedError("Phase 1 implementation pending")

    def get_budget_for_merge(self) -> int:
        """Budget for merge operations (2T = full window)."""
        return self.T * 2

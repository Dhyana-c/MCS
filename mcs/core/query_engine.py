"""Query engine state machine (7 state points).

See architecture.md §2.5.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcs.core.graph import GraphStore, Node
    from mcs.core.token_budget import TokenBudget
    from mcs.interfaces.index import IndexInterface
    from mcs.interfaces.llm import LLMInterface
    from mcs.interfaces.query_hook import QueryHookInterface


class QueryPipelineState(Enum):
    """7 state points emitted by QueryEngine."""

    QUERY_START = "query_start"
    SEEDS_LOCATED = "seeds_located"
    TRAVERSE_START = "traverse_start"
    TRAVERSE_STEP = "traverse_step"
    TRAVERSE_END = "traverse_end"
    SYNTHESIZE_START = "synthesize_start"
    QUERY_END = "query_end"


@dataclass
class QueryContext:
    """Context object passed through one query call."""

    query: str
    seeds: list[Node] | None = None
    current_node: Node | None = None
    accumulated: list[Node] | None = None
    answer: str | None = None
    metadata: dict = field(default_factory=dict)


class QueryEngine:
    """Query engine orchestrator.

    Phase 1 implementation pending. See architecture.md §2.5.
    """

    def __init__(
        self,
        graph: GraphStore,
        llm: LLMInterface,
        index: IndexInterface,
        hooks: list[QueryHookInterface],
        token_budget: TokenBudget,
    ):
        self.graph = graph
        self.llm = llm
        self.index = index
        self.hooks = hooks
        self.token_budget = token_budget

    def _emit(self, state: QueryPipelineState, ctx: QueryContext) -> None:
        """Trigger all hooks for a given state point."""
        method_name = f"on_{state.value}"
        for hook in self.hooks:
            method = getattr(hook, method_name, None)
            if method is not None:
                method(ctx)

    def query(self, query: str, max_tokens: int | None = None) -> str:
        raise NotImplementedError("Phase 1 implementation pending")

    def _locate_seeds(self, query: str) -> list[Node]:
        raise NotImplementedError("Phase 1 implementation pending")

    def _traverse(
        self, ctx: QueryContext, max_tokens: int | None
    ) -> list[Node]:
        raise NotImplementedError("Phase 1 implementation pending")

    def _synthesize(self, query: str, nodes: list[Node]) -> str:
        raise NotImplementedError("Phase 1 implementation pending")

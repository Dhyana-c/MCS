"""Write pipeline state machine (9 state points).

See architecture.md §2.4.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mcs.core.graph import GraphStore, Node
    from mcs.core.token_budget import TokenBudget
    from mcs.interfaces.index import IndexInterface
    from mcs.interfaces.llm import LLMInterface
    from mcs.interfaces.pipeline_hook import PipelineHookInterface


class WritePipelineState(Enum):
    """9 state points emitted by WritePipeline."""

    INGEST_START = "ingest_start"
    EXTRACTED = "extracted"
    PLACE_START = "place_start"
    ANCHORS_FOUND = "anchors_found"
    EXISTENCE_CHECKED = "existence_checked"
    CREATED_OR_MERGED = "created_or_merged"
    FANOUT_CHECKED = "fanout_checked"
    PLACE_END = "place_end"
    INGEST_END = "ingest_end"


@dataclass
class HookContext:
    """Context object passed through one ingest/place call.

    Plugins read and (within their slot) write ctx fields. Setting
    ``ctx.skip = True`` short-circuits the pipeline.
    """

    text: str | None = None
    concepts: list[Any] | None = None
    concept: Any | None = None
    anchors: list[Node] | None = None
    exists: bool | None = None
    existing_node: Node | None = None
    node: Node | None = None
    skip: bool = False
    metadata: dict = field(default_factory=dict)


class WritePipeline:
    """Write pipeline orchestrator.

    Phase 1 implementation pending. See architecture.md §2.4.
    """

    def __init__(
        self,
        graph: GraphStore,
        llm: LLMInterface,
        index: IndexInterface,
        hooks: list[PipelineHookInterface],
        token_budget: TokenBudget,
    ):
        self.graph = graph
        self.llm = llm
        self.index = index
        self.hooks = hooks
        self.token_budget = token_budget

    def _emit(self, state: WritePipelineState, ctx: HookContext) -> None:
        """Trigger all hooks for a given state point."""
        method_name = f"on_{state.value}"
        for hook in self.hooks:
            method = getattr(hook, method_name, None)
            if method is not None:
                method(ctx)

    def ingest(self, text: str, **metadata: Any) -> None:
        raise NotImplementedError("Phase 1 implementation pending")

    def place(
        self, concept: Any, parent_ctx: HookContext | None = None
    ) -> Node:
        raise NotImplementedError("Phase 1 implementation pending")

    def merge_community(self, hub_id: str) -> None:
        raise NotImplementedError("Phase 1 implementation pending")

    def reduce_fanout(self, node_id: str) -> None:
        raise NotImplementedError("Phase 1 implementation pending")

    def _find_anchors(self, concept: Any) -> list[Node]:
        raise NotImplementedError("Phase 1 implementation pending")

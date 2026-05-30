"""Compaction plugin interface - write stage ⑥ conditional cleanup.

See openspec/specs/plugin-protocol/spec.md "CompactionPluginInterface".
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcs.core.graph import GraphStore, Node


class CompactionPluginInterface(ABC):
    """Conditionally cleanup / restructure the graph after ingest.

    Only plugins whose ``should_run`` returns True execute ``run``. Plugins
    receive an ``llm_caller`` handle to issue LLM calls through the unified
    interface when needed (e.g., FanoutReducer calls ``decide_hub``).

    Examples: FanoutReducer (collapse overflowing nodes into a hub),
    CommunityMerger (merge dense regions), SummaryRegen (refresh summaries).
    """

    @abstractmethod
    def should_run(self, changed_nodes: list[Node], graph: GraphStore) -> bool:
        """Return True if this compaction needs to run on the current state."""
        pass

    @abstractmethod
    def run(
        self,
        changed_nodes: list[Node],
        graph: GraphStore,
        llm_caller: Callable,
    ) -> None:
        """Apply the compaction. May modify the graph and issue LLM calls.

        ``llm_caller`` has the signature
        ``call(purpose: str, nodes_in: list[Node], free_args: dict) -> Any``.
        """
        pass

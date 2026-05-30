"""FanoutReducerPlugin - compact a node whose neighborhood exceeds budget.

For each changed node whose 1-hop neighbor count exceeds a threshold,
asks the LLM (``decide_hub`` purpose) which neighbor should become an
intermediate hub. Phase 1 records the chosen hub by promoting the
neighbor's ``role`` to ``"hub"``; full graph surgery (redirecting edges
to form a star) is left for future refinement.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

from mcs.interfaces.compaction_plugin import CompactionPluginInterface
from mcs.plugins.base import Plugin

if TYPE_CHECKING:
    from collections.abc import Callable

    from mcs.core.graph import GraphStore, Node
    from mcs.core.plugin_manager import PluginContext


class FanoutReducerPlugin(Plugin, CompactionPluginInterface):
    """Promote a hub when a node's neighborhood overflows."""

    name: ClassVar[str] = "fanout_reducer"
    version: ClassVar[str] = "0.1.0"
    interfaces: ClassVar[list[type]] = [CompactionPluginInterface]

    def __init__(self, config: dict | None = None) -> None:
        super().__init__(config)
        self.fanout_threshold: int = (config or {}).get("threshold", 12)

    def initialize(self, context: PluginContext) -> None:
        return None

    def shutdown(self) -> None:
        return None

    def should_run(
        self, changed_nodes: list[Node], graph: GraphStore
    ) -> bool:
        for node in changed_nodes:
            neighbors = graph.get_neighbors(node.id)
            if len(neighbors) >= self.fanout_threshold:
                return True
        return False

    def run(
        self,
        changed_nodes: list[Node],
        graph: GraphStore,
        llm_caller: Callable,
    ) -> None:
        for node in changed_nodes:
            neighbors = graph.get_neighbors(node.id)
            if len(neighbors) < self.fanout_threshold:
                continue
            try:
                decision = llm_caller(
                    purpose="decide_hub",
                    nodes_in=[node, *neighbors],
                    free_args={},
                )
            except Exception:
                continue
            if decision is None:
                continue
            hub_id = getattr(decision, "hub_id", None)
            if hub_id and graph.get_node(hub_id) is not None:
                graph.update_node(hub_id, {"role": "hub"})
            elif getattr(decision, "synthetic_hub_summary", None):
                # Phase 1 records the synthetic-hub intent on the focus node.
                reason = getattr(decision, "synthetic_hub_summary", "") or ""
                node.extensions.setdefault("_compaction", {})[
                    "synthetic_hub_summary"
                ] = reason
                graph.update_node(node.id, {"extensions": node.extensions})


_ = Any  # silence unused-import lint when the optional ``Any`` is dropped

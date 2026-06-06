"""CommunityMergerPlugin - Detect and merge dense neighborhoods.

This compaction plugin identifies densely connected node clusters and
creates hub nodes to improve graph navigation and reduce redundancy.

Phase 1 uses a simple lightweight heuristic:
- Find nodes with many neighbors (potential community centers)
- If neighbors share many edges among themselves (high clustering coefficient)
- Create a hub node and reorganize into star topology
"""

from __future__ import annotations

import uuid
from collections import defaultdict
from typing import TYPE_CHECKING, Any

from mcs.core.plugin import PluginType
from mcs.interfaces.compaction_plugin import CompactionPluginInterface

if TYPE_CHECKING:
    from collections.abc import Callable

    from mcs.core.graph import GraphStoreInterface, Node
    from mcs.core.plugin_manager import PluginContext


class CommunityMergerPlugin(CompactionPluginInterface):
    """Detect and merge densely connected node clusters.

    This plugin uses a lightweight heuristic to identify communities:
    1. Find nodes with high degree (potential community centers)
    2. Calculate clustering coefficient of their neighborhoods
    3. If coefficient exceeds threshold, create hub and reorganize

    The goal is to improve cross-document connectivity by creating
    bridge nodes that connect dense clusters.
    """

    def __init__(self, config: dict | None = None) -> None:
        super().__init__(config)
        cfg = config or {}
        # Minimum degree to consider as community center
        self.min_degree: int = cfg.get("min_degree", 10)
        # Minimum clustering coefficient to trigger merge
        self.min_clustering: float = cfg.get("min_clustering", 0.3)
        # Maximum communities to merge per run
        self.max_merges: int = cfg.get("max_merges", 10)
        # Whether to merge cross-document communities only
        self.cross_doc_only: bool = cfg.get("cross_doc_only", True)

    # === Plugin 基类方法 ===

    def get_name(self) -> str:
        return "community_merger"

    # === 插件生命周期 ===

    def initialize(self, context: PluginContext) -> None:
        pass

    def shutdown(self) -> None:
        pass

    # === CompactionPluginInterface ===

    def should_run(self, changed_nodes: list[Node], graph: GraphStoreInterface) -> bool:
        """Check if there are dense communities to merge."""
        # Always check for communities after ingest
        return len(changed_nodes) > 0

    def run(
        self,
        changed_nodes: list[Node],
        graph: GraphStoreInterface,
        llm_caller: Callable,
    ) -> None:
        """Detect and merge communities."""
        # Find all nodes with high degree
        candidates = self._find_community_centers(graph)

        if not candidates:
            return

        # Sort by degree (highest first)
        candidates.sort(key=lambda x: x[1], reverse=True)

        merges_done = 0
        for node, degree in candidates:
            if merges_done >= self.max_merges:
                break

            neighbors = graph.get_neighbors(node.id)
            if len(neighbors) < self.min_degree:
                continue

            # Calculate clustering coefficient
            clustering = self._calc_clustering_coefficient(node.id, neighbors, graph)
            if clustering < self.min_clustering:
                continue

            # Check if cross-document (if required)
            if self.cross_doc_only:
                docs = self._get_neighbor_docs(neighbors)
                if len(docs) <= 1:
                    continue  # Not cross-document

            # Create hub and reorganize
            hub = self._create_hub(node, neighbors, graph, llm_caller)
            if hub:
                self._reorganize_community(node, hub, neighbors, graph)
                merges_done += 1

    def _find_community_centers(self, graph: GraphStoreInterface) -> list[tuple[Node, int]]:
        """Find nodes that could be community centers (high degree)."""
        candidates = []
        for node in graph.get_all_nodes():
            if node.role == "hub":
                continue  # Skip existing hubs
            neighbors = graph.get_neighbors(node.id)
            if len(neighbors) >= self.min_degree:
                candidates.append((node, len(neighbors)))
        return candidates

    def _calc_clustering_coefficient(
        self, node_id: str, neighbors: list[Node], graph: GraphStoreInterface
    ) -> float:
        """Calculate local clustering coefficient.

        For a node with k neighbors, the clustering coefficient is:
        C = (actual edges between neighbors) / (possible edges = k*(k-1)/2)

        High C means neighbors are densely connected (a community).
        """
        if len(neighbors) < 2:
            return 0.0

        neighbor_ids = {n.id for n in neighbors}
        actual_edges = 0

        for neighbor in neighbors:
            for n2 in graph.get_neighbors(neighbor.id):
                if n2.id in neighbor_ids and n2.id > neighbor.id:
                    actual_edges += 1

        possible_edges = len(neighbors) * (len(neighbors) - 1) / 2
        return actual_edges / possible_edges if possible_edges > 0 else 0.0

    def _get_neighbor_docs(self, neighbors: list[Node]) -> set[str]:
        """Get unique document IDs from neighbors."""
        docs = set()
        for n in neighbors:
            sources = n.extensions.get("source_tracking", {}).get("sources", [])
            if sources:
                docs.add(sources[0].get("doc_id", "unknown"))
        return docs

    def _create_hub(
        self,
        center: Node,
        neighbors: list[Node],
        graph: GraphStoreInterface,
        llm_caller: Callable,
    ) -> Node | None:
        """Create a hub node for the community.

        Uses LLM to generate a summary name for the community.
        """
        from mcs.core.graph import Node

        # Use LLM to generate hub name/summary
        try:
            decision = llm_caller(
                purpose="decide_hub",
                nodes_in=[center, *neighbors[:16]],  # Limit to avoid token overflow
                free_args={},
            )
            if decision:
                hub_id = getattr(decision, "hub_id", None)
                if hub_id and graph.get_node(hub_id):
                    # Use existing node as hub
                    graph.update_node(hub_id, {"role": "hub"})
                    return graph.get_node(hub_id)

                summary = getattr(decision, "synthetic_hub_summary", None)
                if summary:
                    hub = Node(
                        id=str(uuid.uuid4()),
                        name=summary[:60],
                        content=summary,
                        role="hub",
                    )
                    graph.add_node(hub)
                    return hub
        except Exception:
            pass

        # Fallback: create hub based on center node
        hub = Node(
            id=str(uuid.uuid4()),
            name=f"Community: {center.name[:40]}",
            content=f"Community hub for nodes related to {center.name}",
            role="hub",
        )
        graph.add_node(hub)
        return hub

    def _reorganize_community(
        self, center: Node, hub: Node, members: list[Node], graph: GraphStoreInterface
    ) -> None:
        """Reorganize community into star topology around hub."""
        # Connect center to hub
        graph.add_edge(center.id, hub.id)

        # Connect members to hub (but keep some edges to center for connectivity)
        for member in members:
            if member.id == hub.id:
                continue
            # Add edge to hub
            graph.add_edge(hub.id, member.id)
            # Optionally keep edge to center (for redundancy)
            # graph.add_edge(center.id, member.id)  # Uncomment to keep

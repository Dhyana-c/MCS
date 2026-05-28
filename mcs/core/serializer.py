"""Subgraph serialization for LLM consumption.

See architecture.md §2.3.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcs.core.graph import Node, Subgraph


class Serializer:
    """Serialize subgraphs into LLM-readable text.

    Phase 1 implementation pending for ``serialize()``; ``get_summary()``
    is implemented so SummaryPlugin-less setups degrade gracefully.
    See architecture.md §2.3.
    """

    def serialize(self, subgraph: Subgraph, mode: str = "full") -> str:
        """Serialize a subgraph.

        mode:
          - "navigation": focus + neighbors + key statements + structural hints
          - "full": outline + cross-references + relevant statements
        """
        raise NotImplementedError("Phase 1 implementation pending")

    def serialize_nodes(self, nodes: list[Node], mode: str = "full") -> str:
        """Serialize a flat list of nodes."""
        raise NotImplementedError("Phase 1 implementation pending")

    @staticmethod
    def get_summary(node: Node) -> str:
        """Read ``node.extensions["summary"]["text"]``, fallback to ``content[:200]``.

        Implemented (not raising) so callers can rely on it even when
        SummaryPlugin is not enabled. See architecture.md §2.3.
        """
        ext = getattr(node, "extensions", None) or {}
        summary_slot = ext.get("summary", {}) if isinstance(ext, dict) else {}
        text = summary_slot.get("text") if isinstance(summary_slot, dict) else None
        if text:
            return text
        content = getattr(node, "content", "") or ""
        return content[:200]

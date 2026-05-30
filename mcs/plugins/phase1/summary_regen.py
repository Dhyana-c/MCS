"""SummaryRegenPlugin - regenerate a node's summary on content change.

Mounted as a CompactionPlugin in write stage ⑥. For each changed node
whose ``extensions["summary"]["text"]`` is missing or stale, calls the
LLM with ``gen_summary`` purpose and updates the slot.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING, ClassVar

from mcs.interfaces.compaction_plugin import CompactionPluginInterface
from mcs.plugins.base import Plugin

if TYPE_CHECKING:
    from collections.abc import Callable

    from mcs.core.graph import GraphStore, Node
    from mcs.core.plugin_manager import PluginContext


class SummaryRegenPlugin(Plugin, CompactionPluginInterface):
    """Refresh ``extensions["summary"]`` for nodes that need it."""

    name: ClassVar[str] = "summary_regen"
    version: ClassVar[str] = "0.1.0"
    interfaces: ClassVar[list[type]] = [CompactionPluginInterface]

    def __init__(self, config: dict | None = None) -> None:
        super().__init__(config)
        self.max_summary_tokens: int = (config or {}).get(
            "max_summary_tokens", 100
        )

    def initialize(self, context: PluginContext) -> None:
        return None

    def shutdown(self) -> None:
        return None

    def should_run(
        self, changed_nodes: list[Node], graph: GraphStore
    ) -> bool:
        return any(self._needs_summary(n) for n in changed_nodes)

    def run(
        self,
        changed_nodes: list[Node],
        graph: GraphStore,
        llm_caller: Callable,
    ) -> None:
        for node in changed_nodes:
            if not self._needs_summary(node):
                continue
            try:
                summary_text = llm_caller(
                    purpose="gen_summary",
                    nodes_in=[node],
                    free_args={"max_tokens": self.max_summary_tokens},
                )
            except Exception:
                continue
            if not isinstance(summary_text, str) or not summary_text.strip():
                continue
            slot = node.extensions.setdefault(
                "summary", {"text": "", "generated_at": None}
            )
            slot["text"] = summary_text.strip()
            slot["generated_at"] = (
                datetime.now(timezone.utc).isoformat()
            )
            slot["_content_len"] = len(node.content or "")
            graph.update_node(node.id, {"extensions": node.extensions})

    def _needs_summary(self, node: Node) -> bool:
        slot = (node.extensions or {}).get("summary", {})
        text = slot.get("text") if isinstance(slot, dict) else None
        if not text:
            return True
        content_len = len(node.content or "")
        return slot.get("_content_len") != content_len

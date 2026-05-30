"""Context rendering - serialize ``List[Node]`` to LLM-readable strings.

Replaces the old ``Serializer.serialize(subgraph, mode)`` API. The new
contract is driven by a ``purpose`` string (one of the 9 LLM purposes);
``NodeExtensionInterface.render(node, purpose)`` lets plugins contribute
extra prompt fragments per purpose.

See openspec/specs/llm-interaction/spec.md.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcs.core.graph import Node
    from mcs.core.plugin_manager import PluginManager
    from mcs.interfaces.node_extension import NodeExtensionInterface


# Purposes that should use summary instead of full content for non-focus nodes.
# Focus node (first in nodes_in) always gets full content.
_SUMMARY_PURPOSES = frozenset(
    {"decide_directions", "decide_hub", "navigate_hub", "extract_concepts"}
)

# Purposes that use summary for ALL nodes (including focus).
_ALL_SUMMARY_PURPOSES = frozenset({"arbitrate"})


class ContextRenderer:
    """Render a list of nodes as LLM-readable text, keyed by purpose.

    Construction takes a ``PluginManager`` so the renderer can find all
    registered ``NodeExtensionInterface`` plugins and invoke their
    ``render(node, purpose)`` to gather contributions.
    """

    def __init__(self, plugin_manager: PluginManager | None = None):
        self.plugin_manager = plugin_manager

    def render(self, nodes_in: list[Node] | None, purpose: str) -> str:
        """Render ``nodes_in`` for the given purpose.

        Empty / None input returns an empty material section. The output
        format is a simple indented outline:

            - <name> (id=<id>)
              <content or summary>
              <extension contributions ...>
        """
        if not nodes_in:
            return "(无)"
        lines: list[str] = []
        extensions = self._get_extensions()
        for idx, node in enumerate(nodes_in):
            is_focus = idx == 0
            lines.append(f"- {node.name} (id={node.id})")
            body = self._select_body(node, purpose, is_focus)
            if body:
                lines.append(f"  {body}")
            for ext in extensions:
                fragment = ext.render(node, purpose)
                if fragment:
                    lines.append(f"  {fragment}")
        return "\n".join(lines)

    def _select_body(self, node: Node, purpose: str, is_focus: bool) -> str:
        """Pick content vs summary based on purpose + focus position."""
        if purpose in _ALL_SUMMARY_PURPOSES:
            return self.get_summary(node)
        if purpose in _SUMMARY_PURPOSES and not is_focus:
            return self.get_summary(node)
        return node.content or self.get_summary(node)

    def _get_extensions(self) -> list[NodeExtensionInterface]:
        """Return all registered NodeExtension plugins (deduped)."""
        if self.plugin_manager is None:
            return []
        from mcs.interfaces.node_extension import NodeExtensionInterface

        return self.plugin_manager.get_all(NodeExtensionInterface)  # type: ignore[return-value]

    @staticmethod
    def get_summary(node: Node) -> str:
        """Read ``node.extensions["summary"]["text"]``; fall back to ``content[:200]``.

        Kept as a static helper so callers can use it without instantiating
        a ContextRenderer (preserved behavior from the old Serializer).
        """
        ext = getattr(node, "extensions", None) or {}
        summary_slot = ext.get("summary", {}) if isinstance(ext, dict) else {}
        text = summary_slot.get("text") if isinstance(summary_slot, dict) else None
        if text:
            return text
        content = getattr(node, "content", "") or ""
        return content[:200]

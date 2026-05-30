"""Node extension interface - plugins extend Node via the extensions dict.

Plugin classes use their ``name`` class attribute (inherited from
``Plugin``) as the key into ``node.extensions[name]``. Implementations
declare what fields they manage and how to serialize them.

In addition to schema/default/serialize/deserialize, extensions MAY
override ``render(node, purpose)`` to contribute a prompt fragment when
``ContextRenderer`` serializes nodes for a specific LLM purpose.

See openspec/specs/plugin-protocol/spec.md "NodeExtensionInterface supports
按 purpose 贡献渲染片段".
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mcs.core.graph import Node


class NodeExtensionInterface(ABC):
    """Abstract node data extension.

    NOTE: ``name`` is provided by the ``Plugin`` base class as a class
    attribute and is the key into ``node.extensions``. It is intentionally
    not an abstract method here to avoid multi-inheritance conflicts.
    """

    @abstractmethod
    def schema(self) -> dict:
        """Field type definitions: ``{field_name: type_str}``."""
        pass

    @abstractmethod
    def default(self) -> Any:
        """Default value for the extension slot on new nodes."""
        pass

    @abstractmethod
    def serialize(self, data: Any) -> dict:
        """Convert extension data to a JSON-serializable dict."""
        pass

    @abstractmethod
    def deserialize(self, data: dict) -> Any:
        """Restore extension data from its serialized form."""
        pass

    # === Optional: prompt rendering contribution ===

    def render(self, node: Node, purpose: str) -> str | None:
        """Contribute a prompt fragment when rendering ``node`` for ``purpose``.

        Default returns None (no contribution). Extensions that want to add
        information beyond the core ``name`` / ``content`` / ``summary``
        fields (e.g., sources, versions, confidence) override this and
        return a short string fragment.

        Return ``None`` when this extension has nothing to contribute for
        the given purpose. ``ContextRenderer`` skips None contributions.
        """
        return None

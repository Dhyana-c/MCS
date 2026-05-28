"""Node extension interface - plugins extend Node via the extensions dict."""

from abc import ABC, abstractmethod
from typing import Any


class NodeExtensionInterface(ABC):
    """Abstract node data extension.

    Plugin classes use their ``name`` class attribute (inherited from
    ``Plugin``) as the key into ``node.extensions[name]``. Implementations
    declare what fields they manage and how to serialize them.

    See architecture.md §3.4.

    NOTE: This interface does not declare ``name()`` as an abstract method
    (although architecture.md §3.4 shows one). The ``name`` identifier is
    instead provided by ``Plugin`` as a class attribute. This avoids a
    multi-inheritance conflict where a class attribute and an abstract method
    would share the same name.
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

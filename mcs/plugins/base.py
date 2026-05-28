"""Plugin base class.

See architecture.md §4.1.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, ClassVar

if TYPE_CHECKING:
    from mcs.core.plugin_manager import PluginContext


class Plugin(ABC):
    """Base class for all MCS plugins.

    Subclasses set these class attributes:

    - ``name`` (str): plugin identifier; also the key into
      ``node.extensions[name]`` for NodeExtension plugins.
    - ``version`` (str): semver string.
    - ``interfaces`` (list[type]): which interfaces this plugin implements
      (used by ``PluginManager.register`` to index the plugin).

    See architecture.md §4.1.
    """

    name: ClassVar[str] = ""
    version: ClassVar[str] = "0.1.0"
    interfaces: ClassVar[list[type]] = []

    def __init__(self, config: dict | None = None) -> None:
        self.config = config or {}

    @abstractmethod
    def initialize(self, context: PluginContext) -> None:
        """Initialize the plugin (called by PluginManager after register)."""
        pass

    @abstractmethod
    def shutdown(self) -> None:
        """Clean up plugin resources."""
        pass

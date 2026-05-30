"""AliasIndexPlugin and AliasEntryPlugin - alias dictionary + entry plugin.

Phase 1 splits the old "all-in-one" AliasIndex into two cleanly-separated
plugins:

- ``AliasIndexPlugin``: implements ``IndexInterface`` + ``NodeExtensionInterface``,
  manages the alias dictionary and ``node.extensions["alias_index"]["aliases"]``.
- ``AliasEntryPlugin``: implements ``EntryPluginInterface``, uses the
  AliasIndex to locate seed nodes at query stage ②.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

from mcs.interfaces.entry_plugin import EntryPluginInterface
from mcs.interfaces.index import IndexInterface
from mcs.interfaces.node_extension import NodeExtensionInterface
from mcs.plugins.base import Plugin
from mcs.utils.tokenizer import ChineseTokenizer

if TYPE_CHECKING:
    from mcs.core.graph import GraphStore, Node
    from mcs.core.plugin_manager import PluginContext


class AliasIndexPlugin(Plugin, IndexInterface, NodeExtensionInterface):
    """Alias dictionary index + node-extension manager.

    Storage: ``self.index`` maps ``term -> set[node_id]`` where ``term``
    is one of the node's name + alias tokens.
    """

    name: ClassVar[str] = "alias_index"
    version: ClassVar[str] = "0.1.0"
    interfaces: ClassVar[list[type]] = [
        IndexInterface,
        NodeExtensionInterface,
    ]

    def __init__(self, config: dict | None = None) -> None:
        super().__init__(config)
        self.index: dict[str, set[str]] = {}
        self.tokenizer: ChineseTokenizer | None = None
        self.graph: GraphStore | None = None

    # === Plugin lifecycle ===

    def initialize(self, context: PluginContext) -> None:
        self.tokenizer = ChineseTokenizer()
        self.graph = context.graph
        self.build(context.graph)

    def shutdown(self) -> None:
        self.index.clear()

    # === NodeExtensionInterface ===

    def schema(self) -> dict:
        return {"aliases": "list[str]"}

    def default(self) -> dict:
        return {"aliases": []}

    def serialize(self, data: Any) -> dict:
        return {"aliases": list(data.get("aliases", []))} if data else {"aliases": []}

    def deserialize(self, data: dict) -> dict:
        return {"aliases": list(data.get("aliases", []))} if data else {"aliases": []}

    # === IndexInterface ===

    def build(self, graph: GraphStore) -> None:
        self.index.clear()
        for node in graph.get_all_nodes():
            self.add_entry(node)

    def lookup(self, query: str) -> list[str]:
        if not query or self.tokenizer is None:
            return []
        node_ids: list[str] = []
        seen: set[str] = set()
        for token in self.tokenizer.tokenize(query):
            for nid in self.index.get(token, set()):
                if nid not in seen:
                    seen.add(nid)
                    node_ids.append(nid)
        return node_ids

    def add_entry(self, node: Node) -> None:
        aliases = (
            node.extensions.get(self.name, {}).get("aliases", []) if node.extensions else []
        )
        for term in [node.name, *aliases]:
            if not term:
                continue
            # Index the full term verbatim.
            self.index.setdefault(term, set()).add(node.id)
            # Also index its tokens so partial-match queries hit. This is what
            # makes "什么是深度学习" find a node named "深度学习" — jieba
            # produces "深度学习" plus its sub-tokens.
            if self.tokenizer is not None:
                for tok in self.tokenizer.tokenize(term):
                    if tok and tok != term:
                        self.index.setdefault(tok, set()).add(node.id)

    def remove_entry(self, node_id: str) -> None:
        empty: list[str] = []
        for term, ids in self.index.items():
            ids.discard(node_id)
            if not ids:
                empty.append(term)
        for term in empty:
            self.index.pop(term, None)

    def update_entry(self, node: Node) -> None:
        self.remove_entry(node.id)
        self.add_entry(node)


class AliasEntryPlugin(Plugin, EntryPluginInterface):
    """Entry plugin: use AliasIndexPlugin's dictionary to locate seed nodes.

    Priority 100 (highest among Phase 1 defaults). Non-exclusive — the
    chain still falls through to ``HubFallbackEntryPlugin`` (priority 0)
    when this returns empty.
    """

    name: ClassVar[str] = "alias_entry"
    version: ClassVar[str] = "0.1.0"
    interfaces: ClassVar[list[type]] = [EntryPluginInterface]
    priority: ClassVar[int] = 100
    exclusive: ClassVar[bool] = False

    def __init__(self, config: dict | None = None) -> None:
        super().__init__(config)
        self.alias_index: AliasIndexPlugin | None = None
        self.graph: GraphStore | None = None

    def initialize(self, context: PluginContext) -> None:
        self.graph = context.graph
        from mcs.interfaces.index import IndexInterface

        idx = context.plugin_manager.get(IndexInterface)
        if isinstance(idx, AliasIndexPlugin):
            self.alias_index = idx

    def shutdown(self) -> None:
        self.alias_index = None

    def locate(self, query: str, ctx: Any) -> list[Node]:
        if self.alias_index is None or self.graph is None:
            return []
        node_ids = self.alias_index.lookup(query)
        nodes: list[Node] = []
        for nid in node_ids:
            node = self.graph.get_node(nid)
            if node is not None:
                nodes.append(node)
        return nodes

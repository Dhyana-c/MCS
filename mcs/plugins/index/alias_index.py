"""AliasIndexPlugin 和 AliasEntryPlugin - 别名字典 + 条目插件。

Phase 1 将旧的"一体化" AliasIndex 拆分为两个清晰分离的插件：

- ``AliasIndexPlugin``: 实现 ``IndexInterface`` + ``NodeExtensionInterface``，
  管理别名字典和 ``node.extensions["alias_index"]["aliases"]``。
- ``AliasEntryPlugin``: 实现 ``EntryPluginInterface``，在查询阶段 ②
  使用 AliasIndex 定位种子节点。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from mcs.core.plugin import PluginType
from mcs.interfaces.entry_plugin import EntryPluginInterface
from mcs.interfaces.index import IndexInterface
from mcs.interfaces.node_extension import NodeExtensionInterface
from mcs.utils.tokenizer import ChineseTokenizer

if TYPE_CHECKING:
    from mcs.core.plugin_manager import PluginContext
    from mcs.core.store import StoreInterface
    from mcs.entities.graph import Node


class AliasIndexPlugin(IndexInterface, NodeExtensionInterface):
    """别名字典索引 + 节点扩展管理器。

    存储: ``self.index`` 映射 ``term -> set[node_id]``，其中 ``term``
    是节点的名称 + 别名词条之一。
    """

    def __init__(self, config: dict | None = None) -> None:
        super().__init__(config)
        self.index: dict[str, set[str]] = {}
        self.tokenizer: ChineseTokenizer | None = None
        self.store: StoreInterface | None = None

    # === Plugin 基类方法 ===

    def get_name(self) -> str:
        return "alias_index"

    def get_type(self) -> PluginType:
        return PluginType.INDEX

    def get_types(self) -> set[PluginType]:
        # 同时实现 Index 与 NodeExtension，两类型都登记
        return {PluginType.INDEX, PluginType.NODE_EXTENSION}

    # === 插件生命周期 ===

    def initialize(self, context: PluginContext) -> None:
        self.tokenizer = ChineseTokenizer()
        self.store = context.store
        self.build(context.store)

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

    def build(self, store: StoreInterface) -> None:
        self.index.clear()
        for node in store.get_all_nodes():
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
            node.extensions.get(self.get_name(), {}).get("aliases", []) if node.extensions else []
        )
        for term in [node.name, *aliases]:
            if not term:
                continue
            # 原样索引完整词条。
            self.index.setdefault(term, set()).add(node.id)
            # 同时索引其分词，以便部分匹配查询命中。这就是
            # 让"什么是深度学习"能找到名为"深度学习"的节点的原因——jieba
            # 会产生"深度学习"及其子词。
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


class AliasEntryPlugin(EntryPluginInterface):
    """条目插件：使用 AliasIndexPlugin 的字典来定位种子节点。

    优先级 100 (Phase 1 默认中最高)。非排他性——当此插件返回
    空结果时，链仍会回退到 ``HubFallbackEntryPlugin`` (优先级 0)。
    """

    def __init__(self, config: dict | None = None) -> None:
        super().__init__(config)
        self.alias_index: AliasIndexPlugin | None = None
        self.store: StoreInterface | None = None

    # === Plugin 基类方法 ===

    def get_name(self) -> str:
        return "alias_entry"

    def get_priority(self) -> int:
        return 100

    @property
    def exclusive(self) -> bool:
        return False

    # === 插件生命周期 ===

    def initialize(self, context: PluginContext) -> None:
        self.store = context.store
        from mcs.core.plugin import PluginType

        idx = context.plugin_manager.get(PluginType.INDEX)
        if isinstance(idx, AliasIndexPlugin):
            self.alias_index = idx

    def shutdown(self) -> None:
        self.alias_index = None

    # === EntryPluginInterface ===

    def locate(self, query: str, ctx: Any) -> list[Node]:
        if self.alias_index is None or self.store is None:
            return []
        node_ids = self.alias_index.lookup(query)
        nodes: list[Node] = []
        for nid in node_ids:
            node = self.store.get_node(nid)
            if node is not None:
                nodes.append(node)
        return nodes

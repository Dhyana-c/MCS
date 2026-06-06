"""索引接口 - 用于种子定位的词法查找。"""

from __future__ import annotations

from abc import abstractmethod
from typing import TYPE_CHECKING

from mcs.core.plugin import Plugin, PluginType

if TYPE_CHECKING:
    from mcs.core.graph import GraphStore, Node


class IndexInterface(Plugin):
    """抽象索引后端。

    为种子定位提供查询字符串到节点ID的查找功能。
    参见 architecture.md §3.2。
    """

    def get_type(self) -> PluginType:
        return PluginType.INDEX

    def execute(self, **kwargs):
        """索引插件无统一执行语义。"""
        raise NotImplementedError("IndexInterface does not support execute()")

    @abstractmethod
    def build(self, graph: GraphStore) -> None:
        """从现有图构建索引。"""
        pass

    @abstractmethod
    def lookup(self, query: str) -> list[str]:
        """返回与查询字符串匹配的节点ID列表。"""
        pass

    @abstractmethod
    def add_entry(self, node: Node) -> None:
        """将节点添加到索引。"""
        pass

    @abstractmethod
    def remove_entry(self, node_id: str) -> None:
        """从索引中移除节点。"""
        pass

    @abstractmethod
    def update_entry(self, node: Node) -> None:
        """更新节点的索引条目。"""
        pass

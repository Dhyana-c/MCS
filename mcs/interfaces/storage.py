"""存储接口 - 图持久化后端的抽象基类。"""

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcs.core.graph import Edge, GraphStore, Node
    from mcs.core.plugin_manager import PluginContext


class StorageInterface(ABC):
    """抽象存储后端。

    实现类将节点和边持久化到持久存储中。
    参见 architecture.md §3.1。
    """

    @abstractmethod
    def initialize(self, context: "PluginContext") -> None:
        """初始化存储。

        实现类应调用
        ``context.plugin_manager.collect_schema_extensions()`` 来动态
        构建其模式（列 + 辅助表）。

        注意：此方法与 ``Plugin.initialize()`` 共享签名，以便
        多重继承子类（Plugin + StorageInterface）只需定义
        一个具体的 ``initialize`` 方法即可同时满足两者。这与
        architecture.md §3.1 中所示的旧签名
        ``initialize(schema_extensions)`` 略有偏差。
        """
        pass

    @abstractmethod
    def save(self, graph: "GraphStore") -> None:
        """持久化整个图（冷快照）。"""
        pass

    @abstractmethod
    def load(self) -> "GraphStore":
        """从存储中加载图。"""
        pass

    @abstractmethod
    def save_node(self, node: "Node") -> None:
        """持久化单个节点。"""
        pass

    @abstractmethod
    def save_edge(self, edge: "Edge") -> None:
        """持久化单条边。"""
        pass

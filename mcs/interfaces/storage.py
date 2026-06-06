"""存储接口 - 图持久化后端的抽象基类。"""

from __future__ import annotations

from abc import abstractmethod
from typing import TYPE_CHECKING

from mcs.core.plugin import Plugin, PluginType

if TYPE_CHECKING:
    from mcs.core.graph import Edge, GraphStoreInterface, Node
    from mcs.core.plugin_manager import PluginContext


class StorageInterface(Plugin):
    """抽象存储后端。

    实现类将节点和边持久化到持久存储中。
    参见 architecture.md §3.1。
    """

    def get_type(self) -> PluginType:
        return PluginType.STORAGE

    def execute(self, **kwargs):
        """存储插件无统一执行语义。"""
        raise NotImplementedError("StorageInterface does not support execute()")

    def initialize(self, context: PluginContext) -> None:
        """初始化存储。

        实现类应调用
        context.plugin_manager.get_all(PluginType.STORAGE_SCHEMA_EXT) 来动态
        构建其模式（列 + 辅助表）。

        注意：此方法与 Plugin.initialize() 共享签名，以便
        多重继承子类只需定义一个具体的 initialize 方法即可同时满足两者。
        """
        pass

    @abstractmethod
    def save(self, graph: GraphStoreInterface) -> None:
        """持久化整个图（冷快照）。"""
        pass

    @abstractmethod
    def load(self) -> GraphStoreInterface:
        """从存储中加载图。"""
        pass

    @abstractmethod
    def save_node(self, node: Node) -> None:
        """持久化单个节点。"""
        pass

    @abstractmethod
    def save_edge(self, edge: Edge) -> None:
        """持久化单条边。"""
        pass

    def commit(self) -> None:
        """提交挂起的写入。

        默认空操作：无事务概念的后端无需实现。事务型后端（如 SQLite）应覆写，
        以便写入管线在每次 ingest 落盘后及时提交（见 write-pipeline 阶段 ⑦）。
        """
        return None

    def save_full(self, graph: GraphStoreInterface) -> None:
        """全量重建持久化：使持久存储与当前内存图完全一致（含删除）。

        增量 save_node / save_edge 只 upsert、不删行，无法反映图手术（如分层
        归纳重挂边）产生的节点/边删除。需要一致快照的场景（如建图收尾）应调用本方法。
        默认回退为 save()（仅追加）；事务型后端（如 SQLite）应覆写为「先清表再整图
        重写」。注意：仅重建图本身（节点/边），不应清理 idempotency 等辅助表。
        """
        self.save(graph)

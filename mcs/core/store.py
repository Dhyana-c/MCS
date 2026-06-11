"""统一存储接口。

``StoreInterface`` 合并了原 ``GraphStoreInterface``（图操作 CRUD + 查询）
和 ``StorageInterface``（持久化 save/load）的全部方法。
具体实现在 ``mcs.stores`` 包中。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcs.core.graph import Edge, Node, Subgraph
    from mcs.core.token_budget import TokenBudget


class StoreInterface(ABC):
    """统一存储抽象基类。

    合并图操作（节点/边 CRUD + 查询）与持久化钩子（save/load/commit/save_full），
    使一个存储后端只需实现一个接口。

    消费者（QueryEngine、WritePipeline、插件等）依赖此接口而非具体实现。
    """

    # === 节点 CRUD ===

    @abstractmethod
    def add_node(self, node: Node) -> str:
        """添加节点，返回节点 id。"""
        ...

    @abstractmethod
    def get_node(self, node_id: str) -> Node | None:
        """按 id 获取节点，不存在返回 None。"""
        ...

    @abstractmethod
    def update_node(self, node_id: str, updates: dict) -> None:
        """更新节点属性。"""
        ...

    @abstractmethod
    def delete_node(self, node_id: str) -> None:
        """删除节点及其关联边。"""
        ...

    # === 边 CRUD ===

    @abstractmethod
    def add_edge(self, source_id: str, target_id: str) -> None:
        """添加有向边 ``source → target``。所有边一律单向。"""
        ...

    @abstractmethod
    def get_edge(self, source_id: str, target_id: str) -> Edge | None:
        """获取两个节点之间的边，不存在返回 None。"""
        ...

    @abstractmethod
    def delete_edge(self, source_id: str, target_id: str) -> None:
        """删除两个节点之间的边。"""
        ...

    def add_bidirectional(self, source_id: str, target_id: str) -> None:
        """一次性添加两条单向边 source→target + target→source（语义边）。

        默认实现调用两次 ``add_edge``；子类可覆写以优化。
        """
        self.add_edge(source_id, target_id)
        self.add_edge(target_id, source_id)

    # === 查询 ===

    @abstractmethod
    def get_neighbors(self, node_id: str) -> list[Node]:
        """获取出邻居：该节点为源的全部有向边目标。"""
        ...

    @abstractmethod
    def get_out_neighbors(self, node_id: str) -> list[Node]:
        """获取出邻居。与 ``get_neighbors`` 同义，保留以减小迁移面。"""
        ...

    @abstractmethod
    def get_subgraph(
        self, node_id: str, token_budget: TokenBudget | None = None
    ) -> Subgraph:
        """从焦点节点贪婪 BFS 扩展，在预算耗尽时停止。"""
        ...

    @abstractmethod
    def get_all_nodes(self) -> list[Node]:
        """返回全部节点。"""
        ...

    @abstractmethod
    def get_all_edges(self) -> list[Edge]:
        """返回全部边。"""
        ...

    # === 持久化钩子 ===

    def save(self) -> None:
        """持久化当前状态。

        默认空操作：无持久化概念的后端（如 InMemoryStore）无需实现。
        事务型后端（如 SQLiteStore）应覆写。
        """
        return None

    def load(self) -> None:
        """从持久层加载（初始化时调用）。

        默认空操作：无持久化概念的后端无需实现。
        事务型后端应覆写，加载节点和边到内存。
        """
        return None

    def commit(self) -> None:
        """提交挂起的写入。

        默认空操作：无事务概念的后端无需实现。事务型后端（如 SQLiteStore）应覆写，
        以便写入管线在每次 ingest 落盘后及时提交。
        """
        return None

    def save_full(self) -> None:
        """全量重建持久化：使持久存储与当前内存图完全一致（含删除）。

        增量 save_node / save_edge 只 upsert、不删行，无法反映图手术（如分层
        归纳重挂边）产生的节点/边删除。需要一致快照的场景（如建图收尾）应调用本方法。
        默认回退为 save()；事务型后端应覆写为「先清表再整图重写」。
        """
        self.save()

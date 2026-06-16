"""统一存储接口。

``StoreInterface`` 合并了原 ``GraphStoreInterface``（图操作 CRUD + 查询）
和 ``StorageInterface``（持久化 save/load）的全部方法。
具体实现在 ``mcs.stores`` 包中。
"""

from __future__ import annotations

import warnings
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcs.core.token_budget import TokenBudget
    from mcs.entities.graph import Edge, Node, Subgraph


class StoreInterface(ABC):
    """统一存储抽象基类。

    合并图操作（节点/边 CRUD + 查询）与持久化钩子（save/load/commit/save_full），
    使一个存储后端只需实现一个接口。

    消费者（QueryEngine、WritePipeline、插件等）依赖此接口而非具体实现。

    边模型随 ``relation_model`` 可插拔：层级边 (kind="hierarchy") 两模式共有；
    ``property_graph`` 模式另有事实边 (kind="fact"，带 label)；
    ``attribute_node`` 模式另有关联边 (kind="assoc"，无 label)。
    事实边 / 关联边一条只存一份，但两端邻接都索引到它（支持反查）。
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
    def add_edge(
        self,
        source_id: str,
        target_id: str,
        kind: str = "hierarchy",
        label: str = "",
        priority: float = 0.0,
    ) -> str:
        """添加有向边 ``source → target``，返回边 id。

        kind MUST 为 "hierarchy"、"fact" 或 "assoc"。
        事实边 label MUST 非空；层级边 / 关联边 label MUST 为空串。
        """
        ...

    @abstractmethod
    def delete_edge(self, edge_id: str) -> None:
        """按边 id 删除边。"""
        ...

    def update_edge(self, edge_id: str, **fields) -> None:
        """更新边属性（kind / label / priority）。

        默认实现：find → replace；子类可覆写以优化。
        """
        raise NotImplementedError("update_edge not implemented")

    # === 层级（骨架）查询 ===

    @abstractmethod
    def get_out_hierarchy(self, node_id: str) -> list[Node]:
        """该节点的层级出边目标（kind="hierarchy" 的 source=node_id 边），驱动导航下钻。"""
        ...

    # === 事实（双向可达）查询 ===

    @abstractmethod
    def get_facts(self, node_id: str, limit: int | None = None) -> list[Edge]:
        """返回该节点作**源或宾**的事实边（反查，双向可达）。

        Phase 2 按 priority 降序、limit 截断 top-K。
        Phase 1 priority 未用，返回全部（limit 仅作可选上限）。
        """
        ...

    def get_out_facts(
        self, node_id: str, limit: int | None = None
    ) -> list[Edge]:
        """该节点为**源**的事实出边。用于 Phase 2 查询视图（fanout 不用，见 spec）。

        Phase 2 用 ``limit`` 截断；Phase 1 不用。默认实现过滤 ``get_facts``；
        子类可覆写以优化。
        """
        out = [e for e in self.get_facts(node_id) if e.source_id == node_id]
        return out[:limit] if limit is not None else out

    @abstractmethod
    def get_assoc(self, node_id: str, limit: int | None = None) -> list[Edge]:
        """返回该节点作**任一端**的 ``kind="assoc"`` 无类型关联边（反查，双向可达）。

        ``property_graph`` 模式通常无 assoc 边、返回空。``limit`` 仅作可选上限。
        """
        ...

    def get_edges_between(self, source_id: str, target_id: str) -> list[Edge]:
        """获取两个节点之间的所有边（不限 kind）。

        替代旧 get_edge(source, target)——新模型下同一对节点可有多条不同 label 的事实边。
        """
        return [
            e
            for e in self.get_all_edges()
            if e.source_id == source_id and e.target_id == target_id
        ]

    # === 旧 API（deprecated，迁移完成后删除） ===

    def get_neighbors(self, node_id: str) -> list[Node]:
        """Deprecated: 迁移到 get_out_hierarchy / get_facts。"""
        warnings.warn(
            "get_neighbors is deprecated; use get_out_hierarchy / get_facts",
            DeprecationWarning,
            stacklevel=2,
        )
        return self.get_out_hierarchy(node_id)

    def get_out_neighbors(self, node_id: str) -> list[Node]:
        """Deprecated: 迁移到 get_out_hierarchy。"""
        warnings.warn(
            "get_out_neighbors is deprecated; use get_out_hierarchy",
            DeprecationWarning,
            stacklevel=2,
        )
        return self.get_out_hierarchy(node_id)

    def get_edge(self, source_id: str, target_id: str) -> Edge | None:
        """Deprecated: 迁移到 get_edges_between。"""
        warnings.warn(
            "get_edge is deprecated; use get_edges_between",
            DeprecationWarning,
            stacklevel=2,
        )
        edges = self.get_edges_between(source_id, target_id)
        return edges[0] if edges else None

    # === 子图 / 全量查询 ===

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

    # === 快照 / 回滚 ===

    def snapshot(self) -> dict:
        """捕获内部图状态快照，供 fanout 裂变失败时整体回滚。

        快照 MUST 保留边 id（回滚后边 id 不变），事务型后端还 MUST 一并捕获
        变更跟踪集——否则增量持久化在回滚后会残留旧行 / 漏删，导致重复边。
        具体存储 MUST 覆写本方法。
        """
        raise NotImplementedError("snapshot not implemented")

    def restore(self, snapshot: dict) -> None:
        """从 ``snapshot()`` 的快照整体还原内部状态（保留边 id）。

        具体存储 MUST 覆写本方法。
        """
        raise NotImplementedError("restore not implemented")

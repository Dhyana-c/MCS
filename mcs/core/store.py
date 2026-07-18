"""统一存储接口（统一图模型）。

``StoreInterface`` 合并了原 ``GraphStoreInterface``（图操作 CRUD + 查询）
和 ``StorageInterface``（持久化 save/load）的全部方法。
具体实现在 ``mcs.stores`` 包中。

统一图模型下边仅 ``关联`` / ``互斥`` 两类（见 ``mcs.entities.graph``）：

  - ``关联``（结构基础边）：连接事实与端点、概念间关联、聚类形成的"组织中心 ↔ 成员"；
    一条只存一份，但两端邻接都索引到它（反查、双向可达）。
  - ``互斥``：事实 ↔ 事实。

**载重规则在存储原语级落实**：``get_relations`` 对核心节点（概念 / 事实）过滤对端为
事件的关联边（事件侧 ``get_relations`` 仍可达核心）——否则"用户 / 我"这类连着海量事件
的节点会把全部事件漏回核心、撑爆活跃视图，且污染 priority 截断样本。
"""

from __future__ import annotations

import warnings
from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

# 事件时间倒排排序键：解析为 epoch 秒比较（naive 视为本地时区），兼容混合形态
# 时间戳（本地裸时间 vs UTC aware）；字典序比较对混合形态排序错误。
from mcs.utils.timestamps import event_sort_key as _event_sort_key

if TYPE_CHECKING:
    from mcs.core.token_budget import TokenBudget
    from mcs.entities.graph import Edge, Node, Subgraph


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

    def get_nodes(self, node_ids: list[str]) -> list[Node]:
        """按 id 批量获取节点（一次取回，缺省跳过、不报错）。

        默认实现逐个 get_node；有索引的存储 SHOULD 覆写以消除 N+1。返回顺序与
        输入一致，不存在的 id 被省略。
        """
        result: list[Node] = []
        for nid in node_ids:
            node = self.get_node(nid)
            if node is not None:
                result.append(node)
        return result

    def get_nodes_by_class(self, node_class: str) -> list[Node]:
        """返回指定 ``node_class`` 的全部节点（定向查询，避免全量加载再过滤）。

        默认实现遍历 ``get_all_nodes`` 过滤；存储 SHOULD 覆写以直接按类索引——
        典型用途：事件层定向查（``recall`` 取近期事件），避免把核心节点也物化进调用方列表。
        """
        return [n for n in self.get_all_nodes() if n.node_class == node_class]

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
        type: str = "关联",
        priority: float = 0.0,
        extensions: dict | None = None,
        edge_id: str | None = None,
    ) -> str:
        """添加有向边 ``source → target``，返回边 id。

        ``type`` MUST 为已登记类型（当前 ``关联`` / ``互斥``，见
        ``mcs.entities.graph.ALLOWED_EDGE_TYPES``）。一条 (source, target, type)
        只存一份，但两端邻接都索引到它（反查、双向可达）。``extensions`` 落到
        ``Edge.extensions``（与 ``Node.extensions`` 对称）。

        ``edge_id`` 非空时用它作边 id（如从 DB 加载历史边时保留原始主键），否则
        mint 新 uuid——使 cross_doc_linker 等需保留既存 id 的场景走公开 API，
        不必绕过本方法去碰 store 内部属性。
        """
        ...

    @abstractmethod
    def delete_edge(self, edge_id: str) -> None:
        """按边 id 删除边。"""
        ...

    def update_edge(self, edge_id: str, **fields) -> None:
        """更新边属性（type / priority）。

        默认实现：find → replace；子类可覆写以优化。
        """
        raise NotImplementedError("update_edge not implemented")

    # === 层级（骨架）查询 ===

    @abstractmethod
    def get_out_hierarchy(
        self, node_id: str, universe: str | None = None
    ) -> list[Node]:
        """该节点的**下钻成员**（驱动导航下钻 / 守门 fanout）。

        统一模型下无独立"层级"边：组织层级由聚类涌现，用 ``关联`` 边 + 中心节点
        ``hub`` 标记表达。故此处返回的是该节点作 source 的 ``关联`` 出边目标
        （即下钻可达的成员）。关系边 token 的有界由查询渲染期按 priority 截断兜。

        ``universe`` 过滤语义 = 按 **target 成员的 universe 单侧判定**（**非**"边两端
        同 universe"）：``universe=U`` 时仅返回 ``target.universe == U`` 的成员；
        ``universe=None`` 返回全部成员（**仅旧库兼容**——多 universe 库 MUST 传当前
        universe，否则 ``__seed_root__`` 视图混入所有 universe 孤儿、破坏单 universe
        活跃视图 ≤ T 不变量）。对普通节点 A 传 ``universe=A.universe`` 恰等价"两端同
        universe"；对 ``__seed_root__``（自身 ``__reality__``）取 ``target.universe==U``
        的孤儿——孤儿挂 root 的边 ``root(__reality__)→孤儿(<work_id>)`` 本身即跨
        universe，"边两端"措辞会误滤掉全部作品孤儿，故 MUST 单侧。
        """
        ...

    # === 关系（双向可达）查询 ===

    @abstractmethod
    def get_relations(self, node_id: str, limit: int | None = None) -> list[Edge]:
        """返回该节点作**任一端**的 ``关联`` / ``互斥`` 边（反查，双向可达）。

        **载重规则（存储原语级落实，双类过滤）**：

        - **同 universe 事件边**（对端 ``事件`` 且两端同 universe）：核心节点
          （``node_class ∈ {概念, 事实}``）MUST 过滤（核心不反查事件）；事件侧
          ``get_relations`` 仍可达核心（**单向过滤**）。
        - **跨 universe 边**（两端 ``universe`` 不同，含跨 universe 的事件背书边）：
          两端节点的 ``get_relations`` 都 MUST NOT 返回（**双向过滤**）——跨 universe
          桥仅经 ``get_cross_universe_edges`` 显式定向查可达，保单 universe 活跃视图封闭。

        互斥边恒为事实 ↔ 事实；跨 universe 互斥边构造上不产生，双向过滤纯属防御。

        Phase 2 按 priority 降序、limit 截断 top-K；Phase 1 priority 未用，
        返回全部（limit 仅作可选上限），返回顺序未定义（依赖底层集合迭代序、
        非稳定排序），调用方不应假设顺序。
        """
        ...

    def get_related_events(
        self,
        node_id: str,
        universe: str | None = None,
        limit: int | None = None,
    ) -> list[Node]:
        """定向查事件：绕过载重规则，返回指向此核心节点的事件节点（时间倒排）。

        宪法载重规则使核心节点 ``get_relations`` 不含事件边（核心不反查）。
        查询需要出处/证据时，用此方法**定向**获取背书此核心节点的事件——独立检索步，
        不进常驻活跃视图、不占 T 预算。

        返回以本节点为 target 的 ``关联`` 边的 source 端中 ``node_class=="事件"``
        的节点列表，按 **时间倒排**（extensions.event_meta.timestamp 降序，
        无 timestamp 的排末尾），Phase 1 limit=None 返回全部。

        ``universe`` 过滤按参数分流（work-narrative-events，MUST NOT 改默认语义）：

        - ``None``（默认）返回**全部**背书事件（含跨 universe）——保
          multi-universe-graph 锁定的"作品 fact 无参查出处（现实摄入事件亦返）"；
        - 传 ``universe=U`` 时只返 ``node.universe==U`` 的事件——叙事时间线
          MUST 显式传 ``universe=work``，避免作品纪年与现实 ISO 混排坏掉。

        时间倒排仅在 ``universe="__reality__"`` 内保证（ISO 可比）；作品 universe
        的事件排序由叙事时间线视图负责（数字年可排，混合纪年 Phase 2 归一化）。

        Args:
            node_id: 核心节点 id
            universe: ``None`` = 全返（含跨 universe）；传值 = 只返该 universe 事件。
            limit: 最多返回的事件数（None = 全部）。用于事件层时间倒排截断。
        """
        # 默认实现：扫全量边找 target==node_id 且 source 为事件的关联边
        node = self.get_node(node_id)
        if node is None:
            return []
        events: list[Node] = []
        for edge in self.get_all_edges():
            if edge.type != "关联":
                continue
            if edge.target_id != node_id:
                continue
            source = self.get_node(edge.source_id)
            if source is not None and source.node_class == "事件":
                if universe is not None and source.universe != universe:
                    continue  # 显式 universe 过滤（None 全返，保 mug 查出处语义）
                events.append(source)
        # 时间倒排：有 timestamp 的排前、降序；无 timestamp 的排末尾
        events.sort(key=_event_sort_key, reverse=True)
        if limit is not None:
            events = events[:limit]
        return events

    def get_cross_universe_edges(
        self, node_id: str, limit: int | None = None
    ) -> list[Edge]:
        """定向查跨 universe 桥（绕载重）：返回该节点作任一端、对端 ``universe`` 不同的
        ``关联`` / ``互斥`` 边，供显式跨 universe 查询受控取数（带 ``limit``）。

        载重规则下这些边在两端 ``get_relations`` 都被双向过滤、不进活跃视图。要取跨
        universe 桥（如 ``演义曹操 —关联— 正史曹操``、现实摄入事件背书作品 fact）MUST 经
        此定向查——它是跨 universe 桥**唯一**的默认载重之外可达路径。

        默认实现扫全量边；有索引的存储（InMemoryStore / SQLiteStore）SHALL 覆写以走邻接
        索引。双实现返回结果 MUST 一致。
        """
        node = self.get_node(node_id)
        if node is None:
            return []
        result: list[Edge] = []
        for edge in self.get_all_edges():
            if node_id not in (edge.source_id, edge.target_id):
                continue
            other_id = edge.target_id if edge.source_id == node_id else edge.source_id
            other = self.get_node(other_id)
            if other is not None and other.universe != node.universe:
                result.append(edge)
        if limit is not None:
            result = result[:limit]
        return result

    def get_edges_between(self, source_id: str, target_id: str) -> list[Edge]:
        """获取两个节点之间的所有边（不限 type）。"""
        return [
            e
            for e in self.get_all_edges()
            if e.source_id == source_id and e.target_id == target_id
        ]

    # === 旧 API（deprecated，迁移完成后删除） ===

    def get_neighbors(self, node_id: str) -> list[Node]:
        """Deprecated: 迁移到 get_out_hierarchy / get_relations。"""
        warnings.warn(
            "get_neighbors is deprecated; use get_out_hierarchy / get_relations",
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

    # === 图级元数据（非节点字段，不进活跃视图 token 口径）===

    @abstractmethod
    def get_graph_meta(self, key: str) -> str | None:
        """取图级元数据；key 不存在返回 None。

        图级 meta 为 key-value、**非节点字段**，MUST NOT 作为节点 content / summary /
        extension，MUST NOT 进入节点活跃视图 token 估算口径（铁律一不受影响）。
        典型用途：图摘要（key="graph_summary"）。
        """
        ...

    @abstractmethod
    def set_graph_meta(self, key: str, value: str) -> None:
        """写 / 覆盖图级元数据。"""
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

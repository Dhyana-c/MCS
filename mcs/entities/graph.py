"""核心图数据结构（统一图模型）。

提供 Node、Edge、Subgraph 数据类，以及节点类 / 边类型的登记常量集。
完整、权威定义见 ``docs/graph-model-design.md``；机制契约见
``openspec/specs/unified-graph-schema/spec.md``。

图操作接口定义在 ``store.py``，具体实现在 ``mcs.stores`` 包中。
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Any

# ── 节点 4 类（按结构行为分，不引入领域 type）─────────────────────────────
# 完整说明见 docs/graph-model-design.md §3.1。领域身份（人物/地点/组织）
# 是 extensions 软标签，不进 node_class。
CLASS_CONCEPT = "概念"   # 名词性事物（人/地点/对象/抽象概念），聚类进核心
CLASS_FACT = "事实"      # 命题：谓词落 content，可被事件背书、可与事实互斥
CLASS_EVENT = "事件"     # 时间轴上的一次发生，规则入库、不经 LLM，不进核心活跃视图
CLASS_SOURCE = "source"  # 原始资料/文件/段落，规则切分分类、保真不改写

#: 全部合法 node_class（登记制；新增须经评审）。
NODE_CLASSES: frozenset[str] = frozenset(
    {CLASS_CONCEPT, CLASS_FACT, CLASS_EVENT, CLASS_SOURCE}
)

#: 核心节点（进核心组织 / 聚类）。事件层不进核心活跃视图（载重规则）。
CORE_NODE_CLASSES: frozenset[str] = frozenset({CLASS_CONCEPT, CLASS_FACT})


def validate_node_class(node_class: str) -> None:
    """登记制校验：``node_class`` 必须属于 :data:`NODE_CLASSES`，否则抛 ``ValueError``。

    与边类型 ``ALLOWED_EDGE_TYPES`` 校验对称——由 store 层在 ``add_node`` /
    ``update_node`` 调用，拦截非法值（如旧模型的 ``attribute``）。
    """
    if node_class not in NODE_CLASSES:
        raise ValueError(
            f"unknown node_class={node_class!r}; "
            f"expected one of {sorted(NODE_CLASSES)}"
        )


# ── 边类型（极简、谨慎增加）──────────────────────────────────────────────
# 见 docs/graph-model-design.md §3.2：取消 kind/label，开放谓词落事实 content。
EDGE_ASSOC = "关联"   # 结构基础边（两端可达）：事实↔端点、概念间关联、组织中心↔成员
EDGE_MUTEX = "互斥"  # 当前唯一语义类型：事实 ↔ 事实

#: 全部合法边 type（登记制；新增语义类型如因果/背书须经评审，不退化为开放字符串）。
ALLOWED_EDGE_TYPES: frozenset[str] = frozenset({EDGE_ASSOC, EDGE_MUTEX})


# ── 持久虚拟根（分层种子图顶点）──────────────────────────────────────────
# 固定 id、永不删除；兜底种子 = 它的（递归）子节点。定义于纯实体模块，
# 避免使用方（hub_fallback / 测试）为引用常量而循环导入 fanout_reducer 插件。
SEED_ROOT_ID = "__seed_root__"
SEED_ROOT_NAME = "__seed_root__"


@dataclass
class Node:
    """图节点（统一模型）。

    ``node_class ∈ {概念, 事实, 事件, source}`` 区分结构行为（聚类 / 双层 / 产生方式），
    **不引入领域 type**——人物/地点/组织等是 ``extensions`` 软标签。

    ``hub`` 仅为**标记**：打在"组织中心"节点上，只用于反查 / 可观测，**无算法含义**、
    非节点类、非 role。渲染给 LLM 时 hub 节点与普通节点无异。按 ``docs/graph-model-design.md
    §3.1``，``hub`` 是 ``extensions`` 的一个开放属性（``extensions["hub"]``），经本类的
    ``hub`` property 读写——存储在 extensions、访问仍用 ``node.hub``。

    所有领域 / 场景字段（别名、摘要、来源、版本、置信度、timestamp、帧……）通过
    ``extensions`` 字典由插件挂载。
    """

    id: str
    name: str
    content: str
    node_class: str = CLASS_CONCEPT  # 概念 / 事实 / 事件 / source
    extensions: dict[str, Any] = field(default_factory=dict)

    @property
    def hub(self) -> bool:
        """组织中心标记（存储于 ``extensions["hub"]``，仅反查 / 可观测，无算法含义）。"""
        return bool((self.extensions or {}).get("hub"))

    @hub.setter
    def hub(self, value: bool) -> None:
        if self.extensions is None:
            self.extensions = {}
        if value:
            self.extensions["hub"] = True
        else:
            self.extensions.pop("hub", None)


@dataclass
class Edge:
    """有向边 ``source → target``（统一模型）。

    边带一个 ``type``，当前仅取 ``关联`` 或 ``互斥``（登记制，详见 ``ALLOWED_EDGE_TYPES``）：

      - **关联**（结构基础边）：连接事实与其端点、概念间一般关联、以及聚类形成的
        "组织中心 ↔ 成员"。两端邻接都索引到它（反查、双向可达）。**无谓词语义**——
        开放谓词落事实节点 content（谓词落点）。
      - **互斥**（当前唯一语义类型）：两条事实相互排斥，事实 ↔ 事实。

    **无 ``kind``、无开放 ``label``、无独立"层级"边**——组织层级由聚类涌现，
    用关联边 + 中心节点 ``hub`` 标记表达。

    ``extensions`` 与 ``Node.extensions`` 对称：插件经 ``EdgeExtensionInterface``
    向其挂载字段，逐条随边保真存取 / 反查 / 重组。``render(edge, purpose)`` 返回
    ``None`` 即该 purpose 下隐藏（字段级可见性）。

    ``priority`` 的**目标态**为派生值——Phase 2 由 ``PriorityScorer`` 从扩展字段算出、
    非写入方权威原语；Phase 1 仅留默认 ``0.0``（``edges.priority`` 列作 Phase 2 派生值缓存）。
    """

    source_id: str
    target_id: str
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    type: str = EDGE_ASSOC          # 关联 / 互斥
    priority: float = 0.0           # 派生值（Phase 2 经 scorer 算）；Phase 1 默认 0.0
    extensions: dict[str, Any] = field(default_factory=dict)


@dataclass
class Subgraph:
    """以焦点节点为根的子图，受 token 预算限制。"""

    focus_id: str
    nodes: list[Node] = field(default_factory=list)
    edges: list[Edge] = field(default_factory=list)


__all__ = [
    # 常量
    "CLASS_CONCEPT",
    "CLASS_FACT",
    "CLASS_EVENT",
    "CLASS_SOURCE",
    "NODE_CLASSES",
    "CORE_NODE_CLASSES",
    "validate_node_class",
    "EDGE_ASSOC",
    "EDGE_MUTEX",
    "ALLOWED_EDGE_TYPES",
    "SEED_ROOT_ID",
    "SEED_ROOT_NAME",
    # 数据类
    "Node",
    "Edge",
    "Subgraph",
]

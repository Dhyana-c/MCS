"""派生优先级打分器（seam，Phase 1 默认 no-op）。

边的 ``priority`` 的**目标态**为派生值——由 ``PriorityScorer`` 从边扩展字段
（创建时间、活跃数等 Phase 2 字段）计算、不作为写入方权威原语。本期（Phase 1）仅引入
seam：``DefaultPriorityScorer`` 固定返回 ``0.0``，行为零变化；Phase 2 在 store 层
chokepoint（``Edge`` 创建处）接入真实 scorer 与衰减打分逻辑。

Phase 1 **不**在写路径调用 scorer、**不**标记 ``add_edge`` / ``Edge.__init__`` 的
``priority`` 参数为 deprecated（其替代 chokepoint 尚未存在）；``edges.priority`` 列
作 Phase 2 派生值缓存保留。

参见 edge-extension-model capability spec "派生优先级（seam）"
与 design D4。
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from mcs.entities.graph import Edge


class PriorityScorer(ABC):
    """边派生优先级打分器接口（目标态权威来源：扩展字段 + scorer）。

    子类实现 ``score(edge)``，依据 ``edge.extensions`` 算出优先级浮点值。
    数值语义（越大越优先 / 越小越优先）由调用方（Phase 2 排序 / 截断）约定。
    """

    @abstractmethod
    def score(self, edge: Edge) -> float:
        """由边扩展字段派生优先级。Phase 1 默认实现返回 ``0.0``。"""
        ...


class DefaultPriorityScorer(PriorityScorer):
    """默认打分器：恒返回 ``0.0``（Phase 1 零行为变化）。

    Phase 1 无可派生字段（活跃数 / 创建时间是 Phase 2 才挂），故返回默认值；
    注入此实例即可拥有"目标态权威来源"的接缝，Phase 2 替换为真实实现。
    """

    def score(self, edge: Edge) -> float:
        return 0.0

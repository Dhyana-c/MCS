"""裁剪插件接口 - 将节点列表缩减以适应 token 预算。

参见 openspec/specs/plugin-protocol/spec.md "TrimPluginInterface"。
"""

from __future__ import annotations

from abc import abstractmethod
from typing import TYPE_CHECKING

from mcs.core.plugin import Plugin, PluginType

if TYPE_CHECKING:
    from mcs.entities.graph import Node


class TrimPluginInterface(Plugin):
    """缩减节点列表，使其预估 token 数适应 budget。

    使用场景：
      - 查询阶段 ② 种子裁剪（入口插件合并后）
      - 查询阶段 ④ 作为 PriorityArbitration 的底层机制

    TrimPlugin 采用链式语义（可注册多个实现，按优先级排序依次执行）。
    每个实现决定如何裁剪：按位置截断（PriorityTrimPlugin）、
    按语义相关性筛选（SemanticTrimPlugin）等。

    基本实现必须保持节点的输入顺序（它们代表优先级）；
    不得重新排序。语义实现（如 SemanticTrimPlugin）可按相关性重排。
    """

    def get_type(self) -> PluginType:
        return PluginType.TRIM

    def execute(self, **kwargs) -> list[Node]:
        """统一入口，委托给 trim()。"""
        return self.trim(
            nodes=kwargs["nodes"],
            budget=kwargs["budget"],
            query=kwargs.get("query", ""),
            ctx=kwargs.get("ctx"),
        )

    @abstractmethod
    def trim(
        self,
        nodes: list[Node],
        budget: int,
        *,
        query: str = "",
        ctx: object | None = None,
    ) -> list[Node]:
        """返回 nodes 的子集，其总预估 token 数 ≤ budget。

        Args:
            nodes: 待裁剪节点列表
            budget: token 预算上限
            query: 原始查询字符串（语义 TrimPlugin 可用于 LLM 筛选）
            ctx: QueryContext（可选，供需要上下文的实现使用）
        """
        pass

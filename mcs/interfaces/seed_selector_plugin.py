"""种子选择器插件接口 - 查询阶段 ② 的种子语义筛选、排序和预算截断。

参见 openspec/specs/seed-selector-plugin/spec.md。
"""

from __future__ import annotations

from abc import abstractmethod
from typing import TYPE_CHECKING, Any

from mcs.core.plugin import Plugin, PluginType

if TYPE_CHECKING:
    from mcs.core.graph import Node
    from mcs.core.query_engine import QueryContext


class SeedSelectorPluginInterface(Plugin):
    """为查询流水线筛选、排序和截断种子节点。

    继承 Plugin，实现 get_type() 返回 SEED_SELECTOR，
    并定义 select() 作为核心方法。

    查询流水线在 TrimPlugin 之后执行 SeedSelectorPlugin 链。
    每个插件的输出成为下一个插件的输入。
    SeedSelector 使用 LLM 语义筛选，选择与查询最相关的种子。

    与 TrimPlugin 的区别：
      - TrimPlugin：硬截断（按优先级截断至预算内）
      - SeedSelector：语义筛选（LLM 判断相关性，可能重排）
    """

    def get_type(self) -> PluginType:
        return PluginType.SEED_SELECTOR

    def execute(self, **kwargs) -> list[Node]:
        """统一入口，委托给 select()。"""
        return self.select(
            seeds=kwargs["seeds"],
            query=kwargs["query"],
            budget=kwargs["budget"],
            ctx=kwargs.get("ctx"),
        )

    @abstractmethod
    def select(
        self,
        seeds: list[Node],
        query: str,
        budget: int,
        ctx: Any | None = None,
    ) -> list[Node]:
        """返回预算内的种子子集，按相关性排序。

        Args:
            seeds: TrimPlugin 输出的种子列表
            query: 用户查询文本
            budget: token 预算上限
            ctx: QueryContext（可选，用于访问中间状态）

        Returns:
            筛选后的种子列表，估算 token 总和 ≤ budget，按相关性降序排列。
        """
        pass
"""种子选择器插件接口 - 已废弃。

语义筛选已合并为 TrimPlugin 实现（SemanticTrimPlugin），
不再需要独立的 SeedSelectorPluginInterface。
保留此文件仅为向后兼容，一个版本后移除。
"""

from __future__ import annotations

from abc import abstractmethod
from typing import TYPE_CHECKING, Any

from mcs.core.plugin import Plugin, PluginType

if TYPE_CHECKING:
    from mcs.core.query_engine import QueryContext
    from mcs.entities.graph import Node


class SeedSelectorPluginInterface(Plugin):
    """已废弃：语义筛选已合并为 TrimPlugin 实现。

    请改用 ``mcs.interfaces.trim_plugin.TrimPluginInterface``，
    并参考 ``mcs.plugins.trim.llm_seed_selector.SemanticTrimPlugin`` 实现。
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
        """已废弃：请改用 TrimPluginInterface.trim()。"""
        pass

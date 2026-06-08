"""LLMSeedSelectorPlugin - 默认的种子语义筛选实现。

使用 LLM (purpose='select_nodes') 从种子中筛选与查询最相关的节点，
按相关性排序并截断至 token 预算内。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from mcs.core.plugin import PluginType
from mcs.interfaces.seed_selector_plugin import SeedSelectorPluginInterface

if TYPE_CHECKING:
    from mcs.core.graph import Node
    from mcs.core.plugin_manager import PluginContext
    from mcs.core.query_engine import QueryContext
    from mcs.interfaces.llm import LLMInterface
    from mcs.core.token_budget import TokenBudget

logger = logging.getLogger(__name__)


class LLMSeedSelectorPlugin(SeedSelectorPluginInterface):
    """使用 LLM 语义筛选种子的默认实现。

    priority=0（默认兜底），用户可注册更高优先级的 SeedSelectorPlugin 替代。
    """

    def __init__(self, config: dict | None = None) -> None:
        super().__init__(config)
        self.llm: LLMInterface | None = None
        self.token_budget: TokenBudget | None = None

    # === Plugin 基类方法 ===

    def get_name(self) -> str:
        return "llm_seed_selector"

    def get_priority(self) -> int:
        return 0

    # === 插件生命周期 ===

    def initialize(self, context: PluginContext) -> None:
        self.token_budget = context.token_budget
        self.llm = context.plugin_manager.get(PluginType.LLM)

    def shutdown(self) -> None:
        self.llm = None
        self.token_budget = None

    # === SeedSelectorPluginInterface ===

    def select(
        self,
        seeds: list[Node],
        query: str,
        budget: int,
        ctx: Any | None = None,
    ) -> list[Node]:
        """使用 LLM 筛选与查询相关的种子，截断至预算内。"""
        if not seeds:
            return []
        if self.llm is None:
            logger.warning("LLMSeedSelectorPlugin 未初始化 LLM，返回原始种子")
            return seeds

        # 调用 LLM 筛选
        selected_ids = self.llm.call(
            purpose="select_nodes",
            nodes_in=seeds,
            free_args={
                "query": query,
                "accumulated_summary": "",
            },
        ) or []

        # 按 LLM 返回顺序构建节点列表
        seed_map = {n.id: n for n in seeds}
        selected: list[Node] = []
        for id_ in selected_ids:
            if id_ in seed_map:
                selected.append(seed_map[id_])

        # 截断至预算内
        if self.token_budget is not None and selected:
            result: list[Node] = []
            used = 0
            for node in selected:
                cost = self.token_budget.estimate_node(node)
                if result and used + cost > budget:
                    break
                result.append(node)
                used += cost
            return result

        return selected
"""SemanticTrimPlugin - 基于 LLM 语义相关性的裁剪实现。

使用 LLM (purpose='select_nodes') 从节点中筛选与查询最相关的节点，
按相关性排序并截断至 token 预算内。作为 TrimPlugin 按需注册。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from mcs.core.plugin import PluginType
from mcs.interfaces.trim_plugin import TrimPluginInterface

if TYPE_CHECKING:
    from mcs.core.plugin_manager import PluginContext
    from mcs.core.query_engine import QueryContext
    from mcs.core.token_budget import TokenBudget
    from mcs.entities.graph import Node
    from mcs.interfaces.llm import LLMInterface

logger = logging.getLogger(__name__)


class SemanticTrimPlugin(TrimPluginInterface):
    """使用 LLM 语义筛选种子的 TrimPlugin 实现。

    按需注册：默认 Phase1 不包含此插件，需要语义筛选时手动注册。
    priority=10（高于 PriorityTrimPlugin 的默认 0），确保语义筛选先执行。
    """

    def __init__(self, config: dict | None = None) -> None:
        super().__init__(config)
        self.llm: LLMInterface | None = None
        self.token_budget: TokenBudget | None = None

    # === Plugin 基类方法 ===

    def get_name(self) -> str:
        return "semantic_trim"

    def get_priority(self) -> int:
        return 10

    # === 插件生命周期 ===

    def initialize(self, context: PluginContext) -> None:
        self.llm = context.plugin_manager.get(PluginType.LLM)
        self.token_budget = context.token_budget

    def shutdown(self) -> None:
        self.llm = None
        self.token_budget = None

    # === TrimPluginInterface ===

    def trim(
        self,
        nodes: list[Node],
        budget: int,
        *,
        query: str = "",
        ctx: QueryContext | None = None,
    ) -> list[Node]:
        """使用 LLM 筛选与查询相关的节点，截断至预算内。

        无 query 时直接按 budget 截断（降级为位置裁剪）。
        """
        if not nodes:
            return []

        # 无 LLM 或无 query 时降级：原样返回（交由后续 TrimPlugin 处理预算）
        if self.llm is None or not query:
            return nodes

        # 调用 LLM 筛选
        selected_ids = self.llm.call(
            purpose="select_nodes",
            nodes_in=nodes,
            free_args={
                "query": query,
                "accumulated_summary": "",
            },
        ) or []

        # 按 LLM 返回顺序构建节点列表
        node_map = {n.id: n for n in nodes}
        selected: list[Node] = []
        for id_ in selected_ids:
            if id_ in node_map:
                selected.append(node_map[id_])

        if not selected:
            return []

        # 截断至预算内
        if self.token_budget is not None:
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

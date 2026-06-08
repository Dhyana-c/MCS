"""PriorityTrimPlugin - 默认的裁剪实现。

按输入顺序（代表优先级）遍历节点，累积 token 估算值，
并在第一个会超出预算的节点处停止。
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from mcs.core.plugin import PluginType
from mcs.interfaces.trim_plugin import TrimPluginInterface

if TYPE_CHECKING:
    from mcs.core.graph import Node
    from mcs.core.plugin_manager import PluginContext
    from mcs.core.token_budget import TokenBudget


class PriorityTrimPlugin(TrimPluginInterface):
    """按优先级顺序保留节点，丢弃超出预算的尾部。"""

    def __init__(self, config: dict | None = None) -> None:
        super().__init__(config)
        self.token_budget: TokenBudget | None = None

    # === Plugin 基类方法 ===

    def get_name(self) -> str:
        return "priority_trim"

    # === 插件生命周期 ===

    def initialize(self, context: PluginContext) -> None:
        self.token_budget = context.token_budget

    def shutdown(self) -> None:
        self.token_budget = None

    # === TrimPluginInterface ===

    def trim(self, nodes: list[Node], budget: int) -> list[Node]:
        if not nodes:
            return []
        result: list[Node] = []
        used = 0
        for node in nodes:
            cost = self._estimate(node)
            if result and used + cost > budget:
                break
            result.append(node)
            used += cost
        return result

    def _estimate(self, node: Node) -> int:
        """估算单个节点的渲染 token（口径与渲染一致）。"""
        if self.token_budget is not None:
            return self.token_budget.estimate_node(node)
        # 未初始化时的回退：使用 ContextRenderer.render_node_full（保守估算）
        from mcs.core.context_renderer import ContextRenderer
        text = ContextRenderer.render_node_full(
            node, purpose="decide_hub", is_focus=True, extensions=None
        )
        return max(1, len(text) // 2)

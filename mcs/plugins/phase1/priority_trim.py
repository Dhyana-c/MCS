"""PriorityTrimPlugin - 默认的裁剪实现。

按输入顺序（代表优先级）遍历节点，累积 token 估算值，
并在第一个会超出预算的节点处停止。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, ClassVar

from mcs.interfaces.trim_plugin import TrimPluginInterface
from mcs.plugins.base import Plugin

if TYPE_CHECKING:
    from mcs.core.graph import Node
    from mcs.core.plugin_manager import PluginContext
    from mcs.core.token_budget import TokenBudget


class PriorityTrimPlugin(Plugin, TrimPluginInterface):
    """按优先级顺序保留节点，丢弃超出预算的尾部。"""

    name: ClassVar[str] = "priority_trim"
    version: ClassVar[str] = "0.1.0"
    interfaces: ClassVar[list[type]] = [TrimPluginInterface]

    def __init__(self, config: dict | None = None) -> None:
        super().__init__(config)
        self.token_budget: TokenBudget | None = None

    def initialize(self, context: PluginContext) -> None:
        self.token_budget = context.token_budget

    def shutdown(self) -> None:
        self.token_budget = None

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
        if self.token_budget is not None:
            return self.token_budget.estimate(node.content or node.name)
        # 未初始化时的回退。
        text = node.content or node.name or ""
        return max(1, len(text) // 2)

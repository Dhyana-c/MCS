"""仲裁插件接口 - 查询阶段 ④ 结果选择。

参见 openspec/specs/plugin-protocol/spec.md "ArbitrationPluginInterface"。
"""

from __future__ import annotations

from abc import abstractmethod
from typing import TYPE_CHECKING, Any

from mcs.core.plugin import Plugin, PluginType

if TYPE_CHECKING:
    from mcs.core.graph import Node


class ArbitrationPluginInterface(Plugin):
    """从 accumulated 中选择最终结果集。

    单一职责：List[Node] -> List[Node]。每个流水线配置最多可注册
    一个 ArbitrationPlugin。

    示例：PriorityArbitration（按优先级硬截断）、LLMArbitration
    （让 LLM 解决版本间的冲突）。
    """

    def get_type(self) -> PluginType:
        return PluginType.ARBITRATION

    def execute(self, **kwargs) -> list[Node]:
        """统一入口，委托给 arbitrate()。"""
        return self.arbitrate(
            accumulated=kwargs["accumulated"],
            query=kwargs["query"],
            ctx=kwargs.get("ctx"),
        )

    @abstractmethod
    def arbitrate(
        self,
        accumulated: list[Node],
        query: str,
        ctx: Any,
    ) -> list[Node]:
        """从累积节点中返回最终结果集。

        输出必须是 List[Node]；此阶段不得修改节点内容
        或产生非 Node 输出。
        """
        pass

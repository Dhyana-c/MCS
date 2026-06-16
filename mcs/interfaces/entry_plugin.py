"""入口插件接口 - 查询阶段 ② 的种子定位。

参见 openspec/specs/plugin-protocol/spec.md "EntryPluginInterface"。
"""

from __future__ import annotations

from abc import abstractmethod
from typing import TYPE_CHECKING, Any

from mcs.core.plugin import Plugin, PluginType

if TYPE_CHECKING:
    from mcs.entities.graph import Node


class EntryPluginInterface(Plugin):
    """为查询流水线定位种子节点。

    继承 Plugin，实现 get_type() 返回 ENTRY，
    并定义 locate() 作为核心方法。

    查询流水线按优先级顺序执行所有已注册的 EntryPlugin。它们的输出
    被合并（按优先级排序）并裁剪以适应 token_budget.T，
    然后进入阶段 ③ 语义循环。
    """

    def get_type(self) -> PluginType:
        return PluginType.ENTRY

    def execute(self, **kwargs) -> Any:
        """统一入口，委托给 locate()。"""
        return self.locate(
            query=kwargs["query"],
            ctx=kwargs.get("ctx"),
        )

    @abstractmethod
    def locate(self, query: str, ctx: Any) -> list[Node]:
        """返回 query 的候选种子节点。

        ctx 是 QueryContext。返回空列表表示此插件未找到任何内容
        —— 链式调用继续到低优先级插件。
        """
        pass

    @property
    def exclusive(self) -> bool:
        """是否独占。默认 False。

        当 exclusive=True 且此插件返回非空结果时，
        框架将跳过优先级更低的 EntryPlugin。
        """
        return False

"""入口插件接口 - 查询阶段 ② 的种子定位。

参见 openspec/specs/plugin-protocol/spec.md "EntryPluginInterface"。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING, Any, ClassVar

if TYPE_CHECKING:
    from mcs.core.graph import Node


class EntryPluginInterface(ABC):
    """为查询流水线定位种子节点。

    子类设置 ``priority``（数值越大优先级越高），并可设置 ``exclusive=True``
    以在非空命中时短路低优先级插件。

    查询流水线按优先级顺序执行所有已注册的 EntryPlugin。它们的输出
    被合并（按优先级排序）并裁剪以适应 ``token_budget.T``，
    然后进入阶段 ③ 语义循环。
    """

    priority: ClassVar[int] = 0
    exclusive: ClassVar[bool] = False

    @abstractmethod
    def locate(self, query: str, ctx: Any) -> list[Node]:
        """返回 ``query`` 的候选种子节点。

        ``ctx`` 是 QueryContext。返回空列表表示此插件未找到任何内容
        —— 链式调用继续到低优先级插件。
        """
        pass

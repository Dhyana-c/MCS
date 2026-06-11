"""压缩插件接口 - 写入阶段 ⑥ 条件清理。

参见 openspec/specs/plugin-protocol/spec.md "CompactionPluginInterface"。
"""

from __future__ import annotations

from abc import abstractmethod
from collections.abc import Callable
from typing import TYPE_CHECKING

from mcs.core.plugin import Plugin, PluginType

if TYPE_CHECKING:
    from mcs.core.graph import Node
    from mcs.core.store import StoreInterface


class CompactionPluginInterface(Plugin):
    """在摄取后有条件地清理/重构图。

    只有 should_run 返回 True 的插件才会执行 run。插件
    接收 llm_caller 句柄，在需要时通过统一接口发起 LLM 调用
    （例如 FanoutReducer 调用 decide_hub）。

    示例：FanoutReducer（将溢出节点折叠为枢纽）、
    CommunityMerger（合并稠密区域）、SummaryRegen（刷新摘要）。
    """

    def get_type(self) -> PluginType:
        return PluginType.COMPACTION

    def execute(self, **kwargs) -> None:
        """统一入口，委托给 run()。"""
        if self.should_run(kwargs.get("changed_nodes", []), kwargs.get("store")):
            self.run(
                changed_nodes=kwargs["changed_nodes"],
                store=kwargs["store"],
                llm_caller=kwargs["llm_caller"],
            )

    @abstractmethod
    def should_run(self, changed_nodes: list[Node], store: StoreInterface) -> bool:
        """如果当前状态需要运行此压缩，则返回 True。"""
        pass

    @abstractmethod
    def run(
        self,
        changed_nodes: list[Node],
        store: StoreInterface,
        llm_caller: Callable,
    ) -> None:
        """应用压缩。可以修改图并发出 LLM 调用。

        llm_caller 的签名为
        call(purpose: str, nodes_in: list[Node], free_args: dict) -> Any。
        """
        pass

    def guard(
        self,
        node: Node,
        store: StoreInterface,
        llm_caller: Callable,
    ) -> None:
        """对单个节点执行守门检查 + 即时裂变（如果超预算）。

        默认为空操作。需要守门的插件（如 FanoutReducer）应覆写此方法。
        框架在 _guard_invariant 中遍历所有 CompactionPlugin 并调用 guard，
        不再 import 具体插件类或调用私有方法。
        """
        return None

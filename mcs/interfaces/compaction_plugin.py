"""压缩插件接口 - 写入阶段 ⑥ 条件清理。

参见 openspec/specs/plugin-protocol/spec.md "CompactionPluginInterface"。
"""

from __future__ import annotations

from abc import abstractmethod
from collections.abc import Callable
from typing import TYPE_CHECKING

from mcs.core.plugin import Plugin, PluginType

if TYPE_CHECKING:
    from mcs.core.store import StoreInterface
    from mcs.entities.graph import Node


class CompactionPluginInterface(Plugin):
    """在摄取后有条件地清理/重构图。

    只有 should_run 返回 True 的插件才会执行 run。插件
    接收 llm_caller 句柄，在需要时通过统一接口发起 LLM 调用
    （例如 FanoutReducer 调用 decide_hub）。

    should_run 负责检查不变量（包括 root 和受影响节点的一跳邻域
    是否超预算），run 负责执行压缩/裂变。

    示例：FanoutReducer（将溢出节点折叠为枢纽）、SummaryRegen（刷新摘要）。
    """

    def get_type(self) -> PluginType:
        return PluginType.COMPACTION

    def execute(self, **kwargs) -> None:
        """统一入口，委托给 run()（should_run 由调用方决定，与 MaintenanceInterface 一致）。"""
        self.run(
            changed_nodes=kwargs["changed_nodes"],
            store=kwargs["store"],
            llm_caller=kwargs["llm_caller"],
        )

    @abstractmethod
    def should_run(self, changed_nodes: list[Node], store: StoreInterface) -> bool:
        """如果当前状态需要运行此压缩，则返回 True。

        实现应在此方法中检查不变量（root + changed + 受影响节点邻域
        是否超预算），以及自身特定的触发条件。
        """
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

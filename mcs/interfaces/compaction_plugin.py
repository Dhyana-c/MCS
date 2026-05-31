"""压缩插件接口 - 写入阶段 ⑥ 条件清理。

参见 openspec/specs/plugin-protocol/spec.md "CompactionPluginInterface"。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from mcs.core.graph import GraphStore, Node


class CompactionPluginInterface(ABC):
    """在摄取后有条件地清理/重构图。

    只有 ``should_run`` 返回 True 的插件才会执行 ``run``。插件
    接收 ``llm_caller`` 句柄，在需要时通过统一接口发起 LLM 调用
    （例如 FanoutReducer 调用 ``decide_hub``）。

    示例：FanoutReducer（将溢出节点折叠为枢纽）、
    CommunityMerger（合并稠密区域）、SummaryRegen（刷新摘要）。
    """

    @abstractmethod
    def should_run(self, changed_nodes: list[Node], graph: GraphStore) -> bool:
        """如果当前状态需要运行此压缩，则返回 True。"""
        pass

    @abstractmethod
    def run(
        self,
        changed_nodes: list[Node],
        graph: GraphStore,
        llm_caller: Callable,
    ) -> None:
        """应用压缩。可以修改图并发出 LLM 调用。

        ``llm_caller`` 的签名为
        ``call(purpose: str, nodes_in: list[Node], free_args: dict) -> Any``。
        """
        pass

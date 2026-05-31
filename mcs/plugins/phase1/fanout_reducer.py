"""FanoutReducerPlugin - 压缩邻域超过预算的节点。

对于每个一跳邻居数超过阈值的变更节点，询问 LLM
（``decide_hub`` 目的）哪个邻居应该成为中间枢纽。
Phase 1 通过将邻居的 ``role`` 提升为 ``"hub"`` 来记录选定的枢纽；
完整的图手术（重定向边以形成星型）留待未来完善。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

from mcs.interfaces.compaction_plugin import CompactionPluginInterface
from mcs.plugins.base import Plugin

if TYPE_CHECKING:
    from collections.abc import Callable

    from mcs.core.graph import GraphStore, Node
    from mcs.core.plugin_manager import PluginContext


class FanoutReducerPlugin(Plugin, CompactionPluginInterface):
    """当节点的邻域溢出时提升枢纽。"""

    name: ClassVar[str] = "fanout_reducer"
    version: ClassVar[str] = "0.1.0"
    interfaces: ClassVar[list[type]] = [CompactionPluginInterface]

    def __init__(self, config: dict | None = None) -> None:
        super().__init__(config)
        self.fanout_threshold: int = (config or {}).get("threshold", 12)

    def initialize(self, context: PluginContext) -> None:
        return None

    def shutdown(self) -> None:
        return None

    def should_run(
        self, changed_nodes: list[Node], graph: GraphStore
    ) -> bool:
        for node in changed_nodes:
            neighbors = graph.get_neighbors(node.id)
            if len(neighbors) >= self.fanout_threshold:
                return True
        return False

    def run(
        self,
        changed_nodes: list[Node],
        graph: GraphStore,
        llm_caller: Callable,
    ) -> None:
        for node in changed_nodes:
            neighbors = graph.get_neighbors(node.id)
            if len(neighbors) < self.fanout_threshold:
                continue
            try:
                decision = llm_caller(
                    purpose="decide_hub",
                    nodes_in=[node, *neighbors],
                    free_args={},
                )
            except Exception:
                continue
            if decision is None:
                continue
            hub_id = getattr(decision, "hub_id", None)
            if hub_id and graph.get_node(hub_id) is not None:
                graph.update_node(hub_id, {"role": "hub"})
            elif getattr(decision, "synthetic_hub_summary", None):
                # Phase 1 在焦点节点上记录合成枢纽意图。
                reason = getattr(decision, "synthetic_hub_summary", "") or ""
                node.extensions.setdefault("_compaction", {})[
                    "synthetic_hub_summary"
                ] = reason
                graph.update_node(node.id, {"extensions": node.extensions})


_ = Any  # 当可选的 ``Any`` 被移除时，消除未使用导入的 lint 警告

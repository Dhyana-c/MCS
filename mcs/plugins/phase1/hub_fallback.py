"""HubFallbackEntryPlugin - 最低优先级的条目插件。

当更高优先级的条目插件（如 AliasEntry）返回空结果时使用。从顶层 hub 节点
出发，按 ``navigate_hub`` purpose 做自顶向下的 LLM 导航，逐层下钻定位种子。

参见 openspec/specs/phase1-defaults/spec.md「全空时 HubFallback 启动 LLM 导航」。
若未配置 LLM 或显式关闭 ``use_llm_navigation``，则优雅降级为直接返回 hub 集合。
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any, ClassVar

from mcs.interfaces.entry_plugin import EntryPluginInterface
from mcs.plugins.base import Plugin

if TYPE_CHECKING:
    from mcs.core.graph import GraphStore, Node
    from mcs.core.plugin_manager import PluginContext


class HubFallbackEntryPlugin(Plugin, EntryPluginInterface):
    """从顶层 hub 自顶向下做 LLM 导航；无 hub 时返回空。"""

    name: ClassVar[str] = "hub_fallback"
    version: ClassVar[str] = "0.1.0"
    interfaces: ClassVar[list[type]] = [EntryPluginInterface]
    priority: ClassVar[int] = 0
    exclusive: ClassVar[bool] = False

    def __init__(self, config: dict | None = None) -> None:
        super().__init__(config)
        cfg = config or {}
        self.graph: GraphStore | None = None
        self.llm: Any = None
        self.max_seeds: int = cfg.get("max_seeds", 10)
        self.max_depth: int = cfg.get("max_depth", 3)
        self.use_llm_navigation: bool = cfg.get("use_llm_navigation", True)

    def initialize(self, context: PluginContext) -> None:
        from mcs.interfaces.llm import LLMInterface

        self.graph = context.graph
        self.llm = context.plugin_manager.get(LLMInterface)

    def shutdown(self) -> None:
        self.graph = None
        self.llm = None

    def locate(self, query: str, ctx: Any) -> list[Node]:
        if self.graph is None:
            return []
        # 优先：从持久虚拟根自顶向下导航（其(递归)子节点即兜底种子）
        from mcs.plugins.phase1.fanout_reducer import SEED_ROOT_ID

        root = self.graph.get_node(SEED_ROOT_ID)
        if root is not None:
            children = self.graph.get_neighbors(root.id)
            if self.llm is None or not self.use_llm_navigation:
                return children[: self.max_seeds]
            landed = [n for n in self._navigate(query, [root]) if n.id != root.id]
            # 导航失败（只剩根）则回退为根的直接子节点；绝不把合成根当种子
            return (landed or children)[: self.max_seeds]
        # 回退：无持久根时用 role==hub 的旧行为
        hubs = [n for n in self.graph.get_all_nodes() if n.role == "hub"]
        if not hubs:
            return []
        if self.llm is None or not self.use_llm_navigation:
            # 优雅降级：无 LLM 或关闭导航时，直接把 hub 当种子。
            return hubs[: self.max_seeds]
        return self._navigate(query, hubs)

    def _navigate(self, query: str, roots: list[Node]) -> list[Node]:
        """从 root hubs 自顶向下逐层 ``navigate_hub`` 下钻。

        每层一次 LLM 调用（输入 = 当前层节点 + 其未访问下属），按返回的下属 id
        继续下钻；``visited`` 防环，``max_depth`` 封顶。返回最终落地节点（若一路
        未下钻成功则回退为 roots）。
        """
        assert self.graph is not None
        visited: set[str] = {n.id for n in roots}
        frontier: list[Node] = list(roots)
        landing: list[Node] = []

        for _depth in range(self.max_depth):
            if not frontier:
                break
            candidates: list[Node] = []
            seen: set[str] = set()
            for node in frontier:
                for neighbor in self.graph.get_neighbors(node.id):
                    if neighbor.id not in visited and neighbor.id not in seen:
                        seen.add(neighbor.id)
                        candidates.append(neighbor)
            if not candidates:
                break

            drill_ids = (
                self.llm.call(
                    purpose="navigate_hub",
                    nodes_in=[*frontier, *candidates],
                    free_args={"target": query},
                )
                or []
            )

            # 整圈候选(本层 examined 的所有节点)一次性标记已访问：BFS 每个节点只
            # 检视一次，避免后续层把同一圈点反复当候选、重复喂给 navigate_hub
            # （双向图下成环/调用爆量的根因）。
            visited.update(seen)

            next_frontier: list[Node] = []
            for cid in drill_ids:
                node = self.graph.get_node(cid)
                if node is not None and cid in seen:  # 必须是本层提出的候选
                    landing.append(node)
                    next_frontier.append(node)
            if not next_frontier:
                break
            frontier = next_frontier

        seeds = landing or list(roots)
        return seeds[: self.max_seeds]

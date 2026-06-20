"""GraphSummaryPlugin - learn 后归纳图级主题摘要。

作为 CompactionPlugin 挂载于写入阶段 ⑥。本次 ingest 产生新概念时，读取
``__seed_root__`` 的顶层 hub（name+content），经 LLM（``gen_graph_summary`` 目的）
语义归纳为图主题摘要（≤ ``max_tokens`` 字），写入图级 meta（key="graph_summary"）。

摘要为图级 meta、**非节点字段**，不进活跃视图 token 口径（铁律一不受影响）。
归纳失败隔离为日志、保留旧摘要、不阻塞 ingest。供记忆 agent 每轮注入 system prompt
作为背景，使「是否进图探索」的路由判断有据。

归纳对象为顶层 hub（经 fanout 收敛的组织中心），非全图——呼应铁律二（归纳必须
LLM 语义，禁止机械拼接 / 空洞聚合标签）。
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from mcs.core.plugin import PluginType
from mcs.entities.graph import CLASS_CONCEPT
from mcs.interfaces.compaction_plugin import CompactionPluginInterface

if TYPE_CHECKING:
    from collections.abc import Callable

    from mcs.core.plugin_manager import PluginContext
    from mcs.core.store import StoreInterface
    from mcs.entities.graph import Node

logger = logging.getLogger(__name__)

# 虚拟根 id（同 MCS 全图约定，见 CLAUDE.md / subgraph-bounding spec）
_SEED_ROOT = "__seed_root__"
# 图级 meta key（图摘要存于 store 图级 meta）
_SUMMARY_KEY = "graph_summary"


class GraphSummaryPlugin(CompactionPluginInterface):
    """learn 后归纳图级主题摘要，写入图级 meta。"""

    def __init__(self, config: dict | None = None) -> None:
        super().__init__(config)
        # 摘要字数预算（与 gen_summary 的 max_tokens 口径一致）；默认 1000 字 ≈ 1k token 量级
        self.max_tokens: int = (config or {}).get("max_tokens", 1000)

    # === Plugin 基类方法 ===

    def get_name(self) -> str:
        return "graph_summary"

    def get_type(self) -> PluginType:
        return PluginType.COMPACTION

    # === 插件生命周期 ===

    def initialize(self, context: PluginContext) -> None:
        return None

    def shutdown(self) -> None:
        return None

    # === CompactionPluginInterface ===

    def should_run(self, changed_nodes: list[Node], store: StoreInterface) -> bool:
        # 本次 ingest 产生新概念（node_class=概念）→ 需刷新图摘要
        return any(
            getattr(n, "node_class", CLASS_CONCEPT) == CLASS_CONCEPT
            for n in changed_nodes
        )

    def run(
        self,
        changed_nodes: list[Node],
        store: StoreInterface,
        llm_caller: Callable,
    ) -> None:
        hubs = store.get_out_hierarchy(_SEED_ROOT)
        # 空图降级：root 无层级子 → 无可归纳对象，不抛异常、保留旧摘要
        if not hubs:
            return
        try:
            summary_text = llm_caller(
                purpose="gen_graph_summary",
                nodes_in=hubs,
                free_args={"max_tokens": self.max_tokens},
            )
        except Exception:
            # 归纳失败隔离：记日志、不阻塞 ingest、保留既有摘要（不覆写 meta）
            logger.warning("gen_graph_summary 失败，保留旧图摘要", exc_info=True)
            return
        if not isinstance(summary_text, str) or not summary_text.strip():
            return
        store.set_graph_meta(_SUMMARY_KEY, summary_text.strip())

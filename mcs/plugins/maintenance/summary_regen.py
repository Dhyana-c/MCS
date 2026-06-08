"""SummaryRegenPlugin - 在内容变更时重新生成节点的摘要。

作为 CompactionPlugin 挂载于写入阶段 ⑥。对于每个变更节点，
如果其 ``extensions["summary"]["text"]`` 缺失或过期，则调用
LLM（``gen_summary`` 目的）并更新该槽位。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import TYPE_CHECKING

from mcs.core.plugin import PluginType
from mcs.interfaces.compaction_plugin import CompactionPluginInterface

if TYPE_CHECKING:
    from collections.abc import Callable

    from mcs.core.graph import Node
    from mcs.core.plugin_manager import PluginContext
    from mcs.core.store import StoreInterface


class SummaryRegenPlugin(CompactionPluginInterface):
    """为需要摘要的节点刷新 ``extensions["summary"]``。"""

    def __init__(self, config: dict | None = None) -> None:
        super().__init__(config)
        self.max_summary_tokens: int = (config or {}).get(
            "max_summary_tokens", 100
        )

    # === Plugin 基类方法 ===

    def get_name(self) -> str:
        return "summary_regen"

    # === 插件生命周期 ===

    def initialize(self, context: PluginContext) -> None:
        return None

    def shutdown(self) -> None:
        return None

    # === CompactionPluginInterface ===

    def should_run(
        self, changed_nodes: list[Node], store: StoreInterface
    ) -> bool:
        return any(self._needs_summary(n) for n in changed_nodes)

    def run(
        self,
        changed_nodes: list[Node],
        store: StoreInterface,
        llm_caller: Callable,
    ) -> None:
        for node in changed_nodes:
            if not self._needs_summary(node):
                continue
            try:
                summary_text = llm_caller(
                    purpose="gen_summary",
                    nodes_in=[node],
                    free_args={"max_tokens": self.max_summary_tokens},
                )
            except Exception:
                continue
            if not isinstance(summary_text, str) or not summary_text.strip():
                continue
            slot = node.extensions.setdefault(
                "summary", {"text": "", "generated_at": None}
            )
            slot["text"] = summary_text.strip()
            slot["generated_at"] = (
                datetime.now(timezone.utc).isoformat()
            )
            slot["_content_len"] = len(node.content or "")
            store.update_node(node.id, {"extensions": node.extensions})

    def _needs_summary(self, node: Node) -> bool:
        slot = (node.extensions or {}).get("summary", {})
        text = slot.get("text") if isinstance(slot, dict) else None
        if not text:
            return True
        content_len = len(node.content or "")
        return slot.get("_content_len") != content_len

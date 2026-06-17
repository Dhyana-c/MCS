"""记忆 agent 的记忆底座 —— MCS 的单线程包装，暴露 query / ingest 文本工具。

MCS 非线程安全、SQLite 连接绑创建线程，故 MCS 的构造与全部调用都经同一个
单 worker 线程（同 ``mcs.mcp.server``）。复用 MCP server 的纯函数渲染 query / ingest
结果，不重复实现。
"""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING, Any, Callable

from mcs.mcp.server import _format_ingest_status, _render_query_result

if TYPE_CHECKING:
    from mcs.core.mcs import MCS


__all__ = ["MemoryStore"]


class MemoryStore:
    """MCS 的单 worker 线程包装，提供 query / ingest 文本接口供 agent 调用。

    Args:
        build_fn: 在 worker 线程内构建并返回 MCS 实例的 callable（SQLite 连接
            绑该 worker 线程）。生产用 ``lambda: Phase1Builder(config).build()``，
            测试可传返回 fake mcs 的 callable。
    """

    def __init__(self, build_fn: Callable[[], "MCS"]) -> None:
        self._executor = ThreadPoolExecutor(
            max_workers=1, thread_name_prefix="mcs-agent-worker"
        )
        self._mcs: MCS = self._submit(build_fn)

    def _submit(self, fn: Callable[..., Any], *args: Any) -> Any:
        """把 fn 提交到单 worker 线程并阻塞等待结果（调用方线程不触碰 MCS）。"""
        return self._executor.submit(fn, *args).result()

    def _do_query(self, query: str) -> str:
        mcs = self._mcs
        result = mcs.query(query)
        return _render_query_result(
            result, mcs.query_engine.relation_model, mcs.read_manager
        )

    def _do_ingest(self, text: str) -> str:
        wctx = self._mcs.ingest(text)
        return _format_ingest_status(wctx)

    def query(self, query: str) -> str:
        """查记忆：跑 mcs.query（worker 线程）→ 渲染为 LLM 可读文本。"""
        return self._submit(self._do_query, query)

    def ingest(self, text: str) -> str:
        """写记忆：跑 mcs.ingest（worker 线程）→ 状态摘要文本。"""
        return self._submit(self._do_ingest, text)

    def shutdown(self) -> None:
        """关闭 MCS（worker 线程内）+ 关闭 executor。"""
        try:
            if hasattr(self._mcs, "shutdown"):
                self._submit(self._mcs.shutdown)
        finally:
            self._executor.shutdown(wait=True)

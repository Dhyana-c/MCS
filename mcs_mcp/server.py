"""MCS MCP（stdio）server —— 把 ingest / query 包成 MCP 工具。

设计要点（见 openspec/changes/mcp-server/design.md）：

- **薄适配**：只消费 MCS 既有公开面（``ingest`` / ``query`` / ``shutdown``）+
  ``MCSConfig.from_file``（config-file-loading），不改核心 / builder / config。
- **单 worker 线程**（``ThreadPoolExecutor(max_workers=1)``）：MCS 非线程安全、SQLite 连接
  绑创建线程，故 MCS 的**构造与全部调用都经同一个单 worker 线程**。单 worker 本身即串行、
  不靠锁（锁只互斥、不保证同线程）。异步工具处理器把每次调用 ``await`` 丢给该 worker，
  不阻塞 stdio 事件循环。
- **mcp 惰性导入**：``mcp`` 包仅在 ``build_fastmcp`` / ``main`` 内按需 import，缺失时报
  ``pip install mcs[mcp]``。这样 ``import mcs_mcp.server``（工具处理函数所在）在 mcp 未装时
  仍可导入，核心库不受影响。

工具处理函数（``MCPServer.run_query`` / ``run_ingest``）**不依赖 mcp SDK**，可独立单测
（不依赖真实 MCP 传输）；结果渲染委托核心库 ``mcs.rendering`` 的公开纯函数
（``render_query_result`` / ``format_ingest_status``）。
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
import threading
from concurrent.futures import ThreadPoolExecutor
from typing import TYPE_CHECKING, Any

from mcs.entities.config import MCSConfig
from mcs.presets import Phase1Builder
from mcs.rendering import format_ingest_status, render_query_result

if TYPE_CHECKING:
    from mcs.core.mcs import MCS

logger = logging.getLogger(__name__)

__all__ = ["MCPServer", "main"]


def _resolve_config_path(argv: list[str] | None) -> str | None:
    """解析配置路径：``--config`` CLI 参数优先，否则取 ``MCS_CONFIG`` 环境变量。"""
    parser = argparse.ArgumentParser(
        prog="mcs-mcp",
        description="MCS MCP server (stdio). Reads a YAML config and serves ingest/query tools.",
    )
    parser.add_argument(
        "--config",
        "-c",
        help="path to MCS YAML config (overrides the MCS_CONFIG env var)",
    )
    args, _ = parser.parse_known_args(argv)
    return args.config or os.environ.get("MCS_CONFIG")


class MCPServer:
    """持有已 build 的 MCS + 单 worker 执行器；串行、线程亲和地服务工具调用。

    工具处理逻辑（``run_query`` / ``run_ingest``）经 ``ThreadPoolExecutor(max_workers=1)``
    串行化到单个 worker 线程，保证：① 调用串行（ingest 与 query 不交错）；② MCS / SQLite
    始终在构造它的同一线程访问；③ 慢 LLM 不阻塞 stdio 事件循环。
    """

    def __init__(self, config_path: str) -> None:
        self._config_path = config_path
        # 单 worker：串行 + 线程亲和（不靠锁）。MCS 在此线程内 build 与调用。
        self._executor = ThreadPoolExecutor(max_workers=1, thread_name_prefix="mcs-mcp-worker")
        self._mcs: MCS | None = None
        self._worker_thread_id: int | None = None
        # 在单 worker 线程内 build MCS（SQLite 连接绑该线程）。
        self._mcs = self._submit(self._build)

    # === worker 内执行 ===

    def _submit(self, fn: Any, *args: Any) -> Any:
        """把 fn 提交到单 worker 线程并阻塞等待结果（调用方线程不触碰 MCS）。"""
        return self._executor.submit(fn, *args).result()

    def _build(self) -> MCS:
        self._worker_thread_id = threading.get_ident()
        config = MCSConfig.from_file(self._config_path)
        return Phase1Builder(config).build()

    def _do_query(self, query: str) -> str:
        assert self._mcs is not None  # build 成功后 _mcs 必非 None
        result = self._mcs.query(query)
        return render_query_result(result, self._mcs.read_manager)

    def _do_ingest(self, text: str) -> str:
        assert self._mcs is not None
        wctx = self._mcs.ingest(text)
        return format_ingest_status(wctx)

    # === 公共：工具处理（串行、线程亲和） ===

    def run_query(self, query: str) -> str:
        """query 工具处理：跑 mcs.query（worker 线程）→ 渲染文本。"""
        return self._submit(self._do_query, query)

    def run_ingest(self, text: str) -> str:
        """ingest 工具处理：跑 mcs.ingest（worker 线程）→ 状态摘要。"""
        return self._submit(self._do_ingest, text)

    # === 生命周期 ===

    def shutdown(self) -> None:
        """进程退出时调用。仅在 MCS 已成功 build（``_mcs`` 非 None）时 shutdown MCS，
        且 shutdown 也在 worker 线程内执行（SQLite 线程亲和）；build 失败时跳过。
        """
        if self._mcs is not None:
            try:
                self._submit(self._shutdown_mcs)
            except Exception:
                logger.warning("MCS shutdown raised", exc_info=True)
        self._executor.shutdown(wait=True)

    def _shutdown_mcs(self) -> None:
        if self._mcs is not None:
            self._mcs.shutdown()


def build_fastmcp(server: MCPServer) -> Any:
    """用 MCP SDK 构建一个 FastMCP server，注册 query / ingest 工具。

    ``mcp`` 缺失时抛含 ``pip install mcs[mcp]`` 指引的 ImportError。工具处理器把每次调用
    ``await`` 丢给 server 的单 worker（串行、不阻塞事件循环）；单次异常隔离为错误响应。
    """
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as exc:
        raise ImportError(
            "the 'mcp' package is required to run the MCP server. "
            "Install it with: pip install mcs[mcp]"
        ) from exc

    import asyncio

    mcp_server = FastMCP("mcs-mcp")

    @mcp_server.tool()
    async def query(query: str) -> str:
        """在 MCS 知识图谱中查询，返回相关节点与关系边的可读文本。

        可能多轮 LLM 调用，耗时较长；调用串行执行。
        """
        try:
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(server._executor, server._do_query, query)
        except Exception as exc:  # 单次异常隔离，server 不崩
            logger.warning("query tool failed", exc_info=True)
            return f"[error] query 失败：{type(exc).__name__}: {exc}"

    @mcp_server.tool()
    async def ingest(text: str) -> str:
        """向 MCS 知识图谱摄入一段文本，自动抽取概念并入图，返回写入状态摘要。

        可能多轮 LLM 调用，耗时较长；调用串行执行。
        """
        try:
            loop = asyncio.get_running_loop()
            return await loop.run_in_executor(server._executor, server._do_ingest, text)
        except Exception as exc:  # 单次异常隔离，server 不崩
            logger.warning("ingest tool failed", exc_info=True)
            return f"[error] ingest 失败：{type(exc).__name__}: {exc}"

    return mcp_server


def main(argv: list[str] | None = None) -> int:
    """MCP server 入口（stdio）。返回退出码。

    读 ``MCS_CONFIG`` 环境变量（或 ``--config`` CLI 参数）指向的 YAML →
    ``MCSConfig.from_file`` → ``Phase1Builder`` build → 经 FastMCP stdio 服务。
    缺配置 / 文件不存在 / build 失败 MUST 清晰报错并以非零码退出。
    """
    config_path = _resolve_config_path(argv)
    if not config_path:
        sys.stderr.write(
            "error: no MCS config. Set the MCS_CONFIG env var or pass --config PATH.\n"
        )
        return 2
    if not os.path.isfile(config_path):
        sys.stderr.write(f"error: config file not found: {config_path}\n")
        return 2

    # mcp 缺失：报含安装指引的错误（早失败）。
    try:
        import mcp  # noqa: F401
    except ImportError:
        sys.stderr.write(
            "error: the 'mcp' package is required to run the MCP server. "
            "Install it with: pip install mcs[mcp]\n"
        )
        return 1

    server: MCPServer | None = None
    try:
        server = MCPServer(config_path)  # 在 worker 线程内 build；失败则 _mcs=None
    except Exception as exc:
        sys.stderr.write(f"error: failed to build MCS from {config_path!r}: {exc}\n")
        return 1

    try:
        mcp_server = build_fastmcp(server)
        mcp_server.run(transport="stdio")
    except KeyboardInterrupt:
        pass
    finally:
        # 仅当 MCS 已成功 build 时 shutdown（server 非 None 且 _mcs 非 None）。
        if server is not None:
            server.shutdown()
    return 0

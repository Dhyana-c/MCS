"""MCS MCP（stdio）server —— 把 query / ingest 包成 MCP 工具（后端走 mcs_agent）。

设计要点（见 openspec/changes/mcp-via-agent/design.md）：

- **后端走 mcs_agent**：``MCPServer`` 持有 ``MemoryAgent``（经 ``create_agent`` 构造）而非
  ``MCS`` 实例。``query`` → ``agent.chat``（ReAct 多步探索、返自然语言答复文本），
  ``ingest`` → ``agent.memory.learn``（``MemoryStore`` 写图原语，不经 agent ReAct loop）。
  ``mcs_mcp`` 不直接 import ``mcs.query`` / ``mcs.ingest`` / ``mcs.presets`` / ``mcs.rendering``。
- **LLM 复用 MCS yaml**：从 ``MCSConfig.plugin_configs`` 反推 ``LLMConfig``（识别
  ``{deepseek,ollama,claude}_llm`` 键），不新增配置文件、不要求 ``AGENT_LLM_*`` env。
- **线程模型**：MCS 的线程亲和 + 串行由 ``MemoryStore`` 自带的单 worker 保证；``mcs_mcp``
  外层仅 ``asyncio.to_thread`` 桥（不阻塞 stdio 事件循环），不自建 executor。
- **shutdown**：进程退出调 ``agent.memory.shutdown()``（worker 内关 MCS + executor）。
- **mcp 惰性 import**：``mcp`` 包仅在 ``build_fastmcp`` / ``main`` 内按需 import，缺失时报
  ``pip install mcs[mcp]``。``import mcs_mcp.server`` 在 mcp 未装时仍可导入（核心库不受影响）。

工具处理函数（``MCPServer.run_query`` / ``run_ingest``）不依赖 mcp SDK，可独立单测
（注入脚本化 agent）；结果来自 ``agent.chat`` / ``agent.memory.learn``。
"""

from __future__ import annotations

import argparse
import logging
import os
import signal
import sys
from typing import Any

from mcs.entities.config import MCSConfig
from mcs_agent.builder import create_agent
from mcs_agent.llms import AGENT_LLM_REGISTRY
from mcs_agent.loop import MemoryAgent

logger = logging.getLogger(__name__)

__all__ = ["MCPServer", "main"]


class _McpConfigError(Exception):
    """mcs_mcp 配置反推失败（无 agent 可用 LLM 插件 / 多 LLM 歧义 / provider 不支持 / 缺字段）。

    ``main`` 捕获 → stderr + ``return 1``，不让 ``AgentBuilder`` 抛裸 ``ValueError``、
    也不静默取错 LLM（防 silent pick wrong LLM）。
    """


def _resolve_config_path(argv: list[str] | None) -> str | None:
    """解析配置路径：``--config`` CLI 参数优先，否则取 ``MCS_CONFIG`` 环境变量。"""
    parser = argparse.ArgumentParser(
        prog="mcs-mcp",
        description="MCS MCP server (stdio). Reads a YAML config and serves query/ingest via mcs_agent.",
    )
    parser.add_argument(
        "--config",
        "-c",
        help="path to MCS YAML config (overrides the MCS_CONFIG env var)",
    )
    args, _ = parser.parse_known_args(argv)
    return args.config or os.environ.get("MCS_CONFIG")


def _llm_config_from_mcs(mcs_config: MCSConfig) -> dict:
    """从 ``MCSConfig.plugin_configs`` 反推 ``create_agent`` 的 ``llm_*`` kwargs + ``mcs_config`` 逃逸口。

    扫以 ``_llm`` 结尾且 provider（去后缀）在 ``AGENT_LLM_REGISTRY`` 的键为候选：

    - 0 候选 → ``_McpConfigError``（无 agent 可用 LLM 插件）。
    - 1 候选 → 取它；若与 ``write_llm`` 不同（``write_llm`` 指向不支持的 provider，如
      ``glm_llm`` + ``deepseek_llm``）→ log warning 提示 agent chat 与 write 管线 LLM 不同
      （有意行为：agent 必须 tool-calling 支持，候选唯一无歧义）。
    - >1 候选 → 按 ``write_llm``（完整插件名，如 ``deepseek_llm``）消歧：``write_llm`` 在候选内
      则取，否则 ``_McpConfigError``（列歧义 + 指引把 ``write_llm`` 指向 agent 支持集之一）。

    选 ``write_llm`` 作消歧锚点因它是 ``MCSConfig`` 必填主写 LLM、是用户最显式指定的 LLM；
    agent 的 ``learn`` 经 MCS 写管线用 ``write_llm``，chat 用同一 LLM 保持写读一致。

    字段映射：deepseek/ollama 取 ``model`` / ``api_key``（默认 ``""``）/ ``base_url``；claude
    优先 ``auth_token``（Bearer）、次选 ``api_key``。``base_url=None`` 时 builder 用
    ``_PROVIDER_DEFAULT_BASE_URL`` 补；不在此硬编码 provider 默认（保 yaml 自定义 base_url）。
    ollama 标准形状无 ``api_key`` → ``""``，本地无鉴权场景 OK。
    """
    pc = mcs_config.plugin_configs
    candidates = [k for k in pc if k.endswith("_llm") and k[:-4] in AGENT_LLM_REGISTRY]
    if not candidates:
        raise _McpConfigError(
            "MCS yaml 未配 agent 可用的 LLM 插件；mcs_mcp 需 plugin_configs 含 "
            f"{sorted(AGENT_LLM_REGISTRY)} 之一的 _llm 段（如 deepseek_llm）"
        )
    if len(candidates) == 1:
        key = candidates[0]
    else:
        wl = mcs_config.write_llm
        key = wl if wl in candidates else None
        if key is None:
            raise _McpConfigError(
                f"MCS yaml 配了多个 agent 可用 LLM {candidates}，且 write_llm={wl!r} 不在其中——"
                f"无法判断 agent chat 该用哪个。请把 write_llm 指向 {sorted(AGENT_LLM_REGISTRY)} 之一"
            )
    if mcs_config.write_llm and mcs_config.write_llm != key:
        logger.warning(
            "agent chat LLM 取 %s（唯一支持的候选），与 write_llm=%s 不同；"
            "agent 需 tool-calling 支持的 provider，write 管线可用其他",
            key,
            mcs_config.write_llm,
        )
    provider = key[:-4]
    cfg = pc[key] or {}
    model = cfg.get("model")
    if not model:
        raise _McpConfigError(f"LLM 插件 {key!r} 缺 model 字段")
    base_url = cfg.get("base_url")
    if provider == "claude":
        auth_token = cfg.get("auth_token")
        api_key = "" if auth_token else cfg.get("api_key", "")
    else:  # deepseek / ollama
        auth_token = None
        api_key = cfg.get("api_key", "")
    return {
        "llm_provider": provider,
        "llm_model": model,
        "llm_api_key": api_key,
        "llm_base_url": base_url,
        "llm_auth_token": auth_token,
        "mcs_config": mcs_config,  # 逃逸口透传，保 yaml 全部配置不丢（prompt_overrides/token_budget/...）
    }


class MCPServer:
    """持有已构造的 ``MemoryAgent``；``query`` / ``ingest`` 委托 agent。

    工具处理（``run_query`` / ``run_ingest``）是同步阻塞调用（含多轮 LLM），MUST 经
    ``asyncio.to_thread`` offload 出 stdio 事件循环（见 ``build_fastmcp``）。MCS 的线程亲和
    + 串行由 ``MemoryStore`` 自带单 worker 保证，本类不自建 executor。
    """

    def __init__(self, config_path: str) -> None:
        self._config_path = config_path
        mcs_config = MCSConfig.from_file(config_path)
        kwargs = _llm_config_from_mcs(mcs_config)  # 早失败（_McpConfigError）
        # create_agent → AgentBuilder.build → MemoryStore(build_fn) 在 MemoryStore worker
        # 线程内 build MCS（SQLite 亲和）。构造同步阻塞秒级，MUST 在 main 同步段调。
        self._agent: MemoryAgent = create_agent(**kwargs)

    @classmethod
    def from_agent(cls, agent: MemoryAgent, config_path: str = "") -> "MCPServer":
        """测试注入路径：直接注入已构造的 ``MemoryAgent``，绕过反推 + ``create_agent``。

        生产走 ``__init__(config_path)``（反推 LLM + ``create_agent``），测试走 ``from_agent``
        （注入脚本化 agent）。两路径分离，不污染生产构造签名。
        """
        server = cls.__new__(cls)
        server._config_path = config_path
        server._agent = agent
        return server

    # === 公共：工具处理（同步阻塞，调用方经 asyncio.to_thread offload） ===

    def run_query(self, query: str) -> str:
        """query 工具处理：``agent.chat`` ReAct 多步探索 → 答复文本（原样透传）。

        调用方 MUST 经 ``asyncio.to_thread`` offload（chat 阻塞、含多轮 LLM）。
        """
        return self._agent.chat(query)

    def run_ingest(self, text: str, work_id: str | None = None) -> str:
        """ingest 工具处理：``agent.memory.learn`` 写图（不经 agent ReAct loop；MCS 写管线内
        LLM 抽取必然）。``learn`` 内部 ``_submit`` 串行化到 MemoryStore worker；同样需 offload。

        ``work_id`` 非空按作品 universe 摄入（透传到 ``learn`` → ``IngestInput.work_id`` →
        ③b 作品叙事事件抽取）；为空走现实 str 归一化（现状不变）。
        """
        return self._agent.memory.learn(text, work_id=work_id)

    # === 生命周期 ===

    def shutdown(self) -> None:
        """进程退出调用。MUST 在 ``main`` 同步 finally 调。``agent.memory.shutdown`` 内：
        worker 线程关 MCS（SQLite 亲和）→ ``executor.shutdown(wait=True)``。"""
        if self._agent is not None:
            try:
                self._agent.memory.shutdown()
            except Exception:
                logger.warning("agent memory shutdown raised", exc_info=True)


def build_fastmcp(server: MCPServer) -> Any:
    """用 MCP SDK 构建一个 FastMCP server，注册 query / ingest 工具。

    ``mcp`` 缺失时抛含 ``pip install mcs[mcp]`` 指引的 ImportError。工具处理器把每次调用
    ``await asyncio.to_thread`` offload（不阻塞事件循环）；单次异常隔离为错误响应。
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
        """在 MCS 记忆图中查询：agent ReAct 多步探索（search→associate→reason 等）后的自然语言答复。

        答复可能含 [id:...] 节点引用；多轮 LLM 调用、耗时较长。偶发返回 agent 降级文本
        （如「达到最大轮次」）属正常、非错误——增大 max_turns 或换支持 tool-calling 的模型可缓解。
        """
        try:
            return await asyncio.to_thread(server.run_query, query)
        except Exception as exc:  # 单次异常隔离，server 不崩
            logger.warning("query tool failed", exc_info=True)
            return f"[error] query 失败：{type(exc).__name__}: {exc}"

    @mcp_server.tool()
    async def ingest(text: str, work_id: str | None = None) -> str:
        """向 MCS 记忆图摄入一段文本（agent.memory.learn 写图原语），返回写入状态摘要。

        自动抽取概念并入图（经 MCS 写管线、含 LLM 抽取阶段）；比 query 快（不经 agent
        ReAct loop）。``work_id`` 非空时按该作品 universe 摄入（触发作品叙事事件抽取）。
        """
        try:
            return await asyncio.to_thread(server.run_ingest, text, work_id)
        except Exception as exc:  # 单次异常隔离，server 不崩
            logger.warning("ingest tool failed", exc_info=True)
            return f"[error] ingest 失败：{type(exc).__name__}: {exc}"

    return mcp_server


def _on_sigterm(signum: Any, frame: Any) -> None:
    """SIGTERM → KeyboardInterrupt，保证 main finally 在强制退出下可达（design D5）。"""
    raise KeyboardInterrupt


def _install_sigterm_handler() -> None:
    """注册 SIGTERM handler（POSIX）。Windows 上 ``signal.SIGTERM`` 有定义、可注册但不会被原生
    发送——注册用 ``try/except`` 包，无害防御。非主线程注册抛 ``ValueError``，同样跳过。"""
    try:
        signal.signal(signal.SIGTERM, _on_sigterm)
    except (ValueError, OSError):
        pass


def main(argv: list[str] | None = None) -> int:
    """MCP server 入口（stdio）。返回退出码。

    读 ``MCS_CONFIG`` 环境变量（或 ``--config`` CLI 参数）指向的 YAML → ``MCSConfig.from_file``
    → 反推 ``LLMConfig`` → ``create_agent`` 构 ``MemoryAgent`` → 经 FastMCP stdio 服务。
    缺配置 / 文件不存在 / mcp 缺失 / 反推失败 / build 失败 MUST 清晰报错并以非零码退出。
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

    _install_sigterm_handler()

    server: MCPServer | None = None
    try:
        server = MCPServer(config_path)  # 反推 + create_agent；失败抛 _McpConfigError 等
    except _McpConfigError as exc:
        sys.stderr.write(f"error: {exc}\n")
        return 1
    except Exception as exc:
        sys.stderr.write(f"error: failed to build agent from {config_path!r}: {exc}\n")
        return 1

    try:
        mcp_server = build_fastmcp(server)
        mcp_server.run(transport="stdio")
    except KeyboardInterrupt:
        pass
    finally:
        # MUST 在 main 同步 finally 调（保证 SQLite 关闭、不留 WAL/锁）。
        if server is not None:
            server.shutdown()
    return 0

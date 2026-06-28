"""记忆 agent 的 FastAPI 对话后端（基础 app）。

- ``create_app(agent)``：接受任意带 ``chat(user_message) -> str`` 的 agent，挂 ``/chat``、
  ``/health``、``/graph/expand`` 基础路由 + 静态前端（``static/index.html``、``graph.html``）。
  仅基础 agent 能力——个人记忆功能（碎片 / 整合 / 日记 / 召回 / 管理看板）由独立包 ``mcs_mem``
  扩展（``mcs_mem.create_app`` 自建 app、复用本模块的 ``register_base_routes``）。
- ``register_base_routes(app, agent)``：基础路由注册，供 ``create_app`` 与 ``mcs_mem`` 复用。
- ``build_agent_from_env()``：从环境变量构建生产 ``MemoryAgent``（经 ``AgentBuilder``）。
- ``run()``：起 uvicorn（基础 agent app；记忆应用入口在 ``mcs_mem.run``）。
"""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Protocol

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from mcs.entities.config import MCSConfig
from mcs_agent.builder import AgentBuilder, AgentConfig, LLMConfig
from mcs_agent.loop import MemoryAgent
from mcs_agent.trace import ChatTrace

__all__ = [
    "create_app",
    "register_base_routes",
    "build_agent_from_env",
    "run",
    "ChatRequest",
    "ChatResponse",
]

_trace_logger = logging.getLogger(__name__ + ".trace")
_trace_logger.setLevel(logging.INFO)
# 确保 trace 日志在默认部署下可见（root logger 默认 WARNING 会丢弃 INFO）。
# 若已有 handler（如外部 dictConfig），避免重复输出。
if not _trace_logger.handlers:
    _trace_logger.addHandler(logging.StreamHandler())
    _trace_logger.propagate = False  # 自挂 handler 后关冒泡，避免 root 也配 handler 时双打


class ChatRequest(BaseModel):
    message: str


class ChatResponse(BaseModel):
    reply: str


class _AgentProto(Protocol):
    def chat(self, user_message: str) -> str: ...


def register_base_routes(app: FastAPI, agent: _AgentProto) -> None:
    """注册基础路由（``/chat`` / ``/health`` / ``/graph/expand``）。

    供 ``create_app`` 与 ``mcs_mem.create_app`` 复用，避免基础路由重复定义。
    MUST 在 StaticFiles mount ``/`` **之前**调用——否则兜底 mount 会拦截这些 API 路由。
    """

    @app.get("/health")
    def health() -> dict[str, Any]:
        return {"ok": True}

    @app.post("/chat", response_model=ChatResponse)
    def chat(req: ChatRequest) -> ChatResponse:
        reply = agent.chat(req.message)
        return ChatResponse(reply=reply)

    @app.get("/graph/expand")
    def graph_expand(node_id: str = "__seed_root__") -> dict:
        """只读图谱可视化端点：转发到 ``agent.memory.graph_view``（缺省虚拟根）。

        线程安全由 ``MemoryStore._submit`` 保证（路由线程不直接触碰 mcs / store）。
        优雅降级：注入的 agent 无 ``memory`` 或 ``memory`` 无 ``graph_view`` 时
        （如裸 fake agent）返回 503，不影响既有 ``/chat``。节点不存在 → 404。
        """
        graph_view = getattr(getattr(agent, "memory", None), "graph_view", None)
        if not callable(graph_view):
            raise HTTPException(status_code=503, detail="graph view unavailable")
        result = graph_view(node_id)
        if result is None:
            raise HTTPException(status_code=404, detail="node not found")
        return result


def create_app(agent: _AgentProto) -> FastAPI:
    """构建基础 FastAPI app：``/chat``、``/health``、``/graph/expand`` + 静态前端兜底。

    仅基础 agent 能力。个人记忆功能由 ``mcs_mem.create_app`` 在此基础上扩展
    （``mcs_mem`` → ``mcs_agent`` 单向依赖；本模块不 import ``mcs_mem``）。
    """
    app = FastAPI(title="MCS Memory Agent")
    app.state.agent = agent

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    register_base_routes(app, agent)

    # 静态前端兜底挂载（API 路由已先注册，优先匹配）
    static_dir = Path(__file__).parent / "static"
    if static_dir.is_dir():
        app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")

    return app


def build_agent_from_env() -> MemoryAgent:
    """从环境变量构建生产 ``MemoryAgent``（经 ``AgentBuilder``）。

    需要：
      - ``MCS_CONFIG``：MCS yaml 配置路径（→ ``mcs_config`` 逃逸口，MCS LLM 由 yaml 决定）。
      - ``AGENT_LLM_API_KEY`` / ``AGENT_LLM_MODEL`` /（可选）``AGENT_LLM_BASE_URL`` /
        ``AGENT_LLM_PROVIDER``（默认 ``deepseek``）：agent chat LLM（→ ``LLMConfig``）。

    缺关键变量时以非零码退出（``SystemExit``），早失败。env 契约逐字保留。
    """

    def _on_trace(chat_trace: ChatTrace) -> None:
        # 结构化 + 脱敏：仅聚合指标（调用数 / token / 延迟 / 工具名），不含用户原文。
        summary = {
            "llm_calls": len(chat_trace.llm_calls),
            "tool_calls": len(chat_trace.tool_calls),
            "tool_names": [t.tool_name for t in chat_trace.tool_calls],
            "total_latency_ms": round(chat_trace.total_latency_ms, 1),
            "total_tokens": chat_trace.total_tokens,
            "user_message_len": len(chat_trace.user_message),
            "reply_len": len(chat_trace.reply),
        }
        _trace_logger.info("ChatTrace: %s", json.dumps(summary, ensure_ascii=False))

    config_path = os.environ.get("MCS_CONFIG")
    if not config_path:
        raise SystemExit("MCS_CONFIG env var not set (path to MCS yaml config).")
    api_key = os.environ.get("AGENT_LLM_API_KEY", "")
    if not api_key:
        raise SystemExit("AGENT_LLM_API_KEY env var not set.")
    model = os.environ.get("AGENT_LLM_MODEL", "deepseek-chat")
    base_url = os.environ.get("AGENT_LLM_BASE_URL") or None
    provider = os.environ.get("AGENT_LLM_PROVIDER", "deepseek")

    mcs_config = MCSConfig.from_file(config_path)
    llm = LLMConfig(provider=provider, model=model, api_key=api_key, base_url=base_url)
    config = AgentConfig(llm=llm, mcs_config=mcs_config, on_trace=_on_trace)
    return AgentBuilder(config).build()


def run(host: str = "127.0.0.1", port: int = 8000) -> None:
    """构建 agent 并启动 uvicorn（基础 agent app；记忆应用入口见 ``mcs_mem.run``）。"""
    import uvicorn

    agent = build_agent_from_env()
    app = create_app(agent)
    uvicorn.run(app, host=host, port=port)

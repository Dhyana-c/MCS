"""记忆 agent 的 FastAPI 对话后端。

- ``create_app(agent)``：接受任意带 ``chat(user_message) -> str`` 的 agent（可注入
  fake，便于测试），挂 ``/chat``、``/health`` 路由 + 静态前端（``static/index.html``）。
- ``build_agent_from_env()``：从环境变量构建生产 ``MemoryAgent``（``MemoryStore``
  经 ``Phase1Builder`` build + openai 兼容 ``llm_call``）。
- ``run()``：起 uvicorn。
"""

from __future__ import annotations

import dataclasses
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

__all__ = ["create_app", "build_agent_from_env", "run", "ChatRequest", "ChatResponse"]

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


def create_app(agent: _AgentProto) -> FastAPI:
    """构建 FastAPI app：``/chat``、``/health`` API + 静态前端兜底。

    API 路由先注册、优先匹配；``StaticFiles`` 挂在 ``/`` 兜底（访问 ``/`` 返回
    ``index.html``）。CORS 开发期全开，生产按域名收紧。
    """
    app = FastAPI(title="MCS Memory Agent")
    app.state.agent = agent

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

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

    缺关键变量时以非零码退出（``SystemExit``），早失败。env 契约逐字保留（change
    memory-agent-builder D8）。
    """

    def _on_trace(chat_trace: ChatTrace) -> None:
        # TODO: request_summary 含用户原文预览，多轮对话会重复累积；需评估脱敏/限条数
        # TODO: 当前输出 Python dict str()，非 JSON；换 json formatter 后自动解决
        _trace_logger.info("ChatTrace: %s", dataclasses.asdict(chat_trace))

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
    """构建 agent 并启动 uvicorn（``uvicorn`` 惰性 import，测试不需）。"""
    import uvicorn

    agent = build_agent_from_env()
    app = create_app(agent)
    uvicorn.run(app, host=host, port=port)

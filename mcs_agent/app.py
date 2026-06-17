"""记忆 agent 的 FastAPI 对话后端。

- ``create_app(agent)``：接受任意带 ``chat(user_message) -> str`` 的 agent（可注入
  fake，便于测试），挂 ``/chat``、``/health`` 路由 + 静态前端（``static/index.html``）。
- ``build_agent_from_env()``：从环境变量构建生产 ``MemoryAgent``（``MemoryStore``
  经 ``Phase1Builder`` build + openai 兼容 ``llm_call``）。
- ``run()``：起 uvicorn。
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Protocol

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from mcs.entities.config import MCSConfig
from mcs.presets import Phase1Builder
from mcs_agent.llm import make_openai_llm_call
from mcs_agent.loop import MemoryAgent
from mcs_agent.memory import MemoryStore

__all__ = ["create_app", "build_agent_from_env", "run", "ChatRequest", "ChatResponse"]


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

    # 静态前端兜底挂载（API 路由已先注册，优先匹配）
    static_dir = Path(__file__).parent / "static"
    if static_dir.is_dir():
        app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")

    return app


def build_agent_from_env() -> MemoryAgent:
    """从环境变量构建生产 ``MemoryAgent``。

    需要：
      - ``MCS_CONFIG``：MCS yaml 配置路径（``MemoryStore`` 经 ``Phase1Builder`` build）。
      - ``AGENT_LLM_API_KEY`` / ``AGENT_LLM_MODEL`` /（可选）``AGENT_LLM_BASE_URL``：
        agent 自有 LLM（openai 兼容端点）。

    缺关键变量时以非零码退出（``SystemExit``），早失败。
    """
    config_path = os.environ.get("MCS_CONFIG")
    if not config_path:
        raise SystemExit("MCS_CONFIG env var not set (path to MCS yaml config).")
    api_key = os.environ.get("AGENT_LLM_API_KEY", "")
    model = os.environ.get("AGENT_LLM_MODEL", "deepseek-chat")
    base_url = os.environ.get("AGENT_LLM_BASE_URL") or None
    if not api_key:
        raise SystemExit("AGENT_LLM_API_KEY env var not set.")

    config = MCSConfig.from_file(config_path)

    def _build_mcs() -> Any:
        return Phase1Builder(config).build()

    memory = MemoryStore(_build_mcs)
    llm_call = make_openai_llm_call(model, api_key, base_url)
    return MemoryAgent(memory, llm_call)


def run(host: str = "127.0.0.1", port: int = 8000) -> None:
    """构建 agent 并启动 uvicorn（``uvicorn`` 惰性 import，测试不需）。"""
    import uvicorn

    agent = build_agent_from_env()
    app = create_app(agent)
    uvicorn.run(app, host=host, port=port)

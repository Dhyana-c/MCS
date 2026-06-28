"""个人记忆应用（mcs_mem）——在 mcs_agent 基础路由之上扩展记忆功能。

依赖方向：``mcs_mem`` → ``mcs_agent`` → ``mcs``（单向）。

``create_app(agent, fragment_store=None)`` 自建 FastAPI app：
  1. 注册记忆路由（碎片 / 整合 / 日记 / 召回）+ ``/manage.html``；
  2. 复用 ``mcs_agent.register_base_routes``（``/chat`` / ``/health`` / ``/graph/expand``）；
  3. 设 scheduler lifespan（随 app 起停）；
  4. **最后** mount StaticFiles（``mcs_agent/static`` 兜底 ``index.html`` / ``graph.html``）。

记忆路由 + ``/manage.html`` MUST 在 StaticFiles mount 之前注册——否则 ``/`` 兜底 mount
会拦截这些路径。``run`` 委托 ``mcs_agent.build_agent_from_env`` 构造 agent。
"""

from __future__ import annotations

import logging
import os
from contextlib import asynccontextmanager
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Protocol

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from mcs_agent import app as _mcs_agent_app
from mcs_agent.app import register_base_routes
from mcs_agent.loop import MemoryAgent
from mcs_agent.tools import READONLY_TOOL_NAMES, ToolsetConfig

from mcs_mem.consolidation import ConsolidationTracker, Consolidator, LLMDenoiser
from mcs_mem.diary import DiaryGenerator, DiaryStore
from mcs_mem.fragments import FragmentStore, VersionMismatch
from mcs_mem.scheduler import ConsolidationScheduler

__all__ = ["create_app", "run"]

logger = logging.getLogger(__name__)


# === pydantic models（记忆端点契约） ===


class NoteRequest(BaseModel):
    content: str


class NoteResponse(BaseModel):
    ok: bool
    date: str
    time: str


class FragmentListResponse(BaseModel):
    fragments: list[str]


class FragmentContentResponse(BaseModel):
    date: str
    content: str
    mtime: float | None = None


class FragmentPutRequest(BaseModel):
    content: str
    expected_mtime: float | None = None


class FragmentPutResponse(BaseModel):
    ok: bool
    date: str


class ConsolidateRequest(BaseModel):
    date: str | None = None


class ConsolidateResponse(BaseModel):
    ok: bool
    date: str
    status: str
    events: int
    warning: str | None = None


class DiaryRequest(BaseModel):
    date: str | None = None


class DiaryGenerateResponse(BaseModel):
    ok: bool
    date: str
    reason: str | None = None


class DiaryContentResponse(BaseModel):
    date: str
    content: str


class DiaryListResponse(BaseModel):
    diaries: list[str]


class RecallRequest(BaseModel):
    message: str


class RecallResponse(BaseModel):
    reply: str


class _AgentProto(Protocol):
    def chat(self, user_message: str) -> str: ...


def create_app(agent: _AgentProto, fragment_store: FragmentStore | None = None) -> FastAPI:
    """构建个人记忆应用 app（基础路由 + 记忆路由 + 管理看板 + scheduler）。

    Args:
        agent: 带 ``chat`` 的 agent（生产 ``MemoryAgent``，含 ``memory`` / ``llm``）。
        fragment_store: 碎片存储；None 自动构造（默认目录或 env）。
    """
    app = FastAPI(title="MCS Memory (mcs_mem)")
    app.state.agent = agent

    # FragmentStore：捕获端点不依赖 agent / MCS（纯文件 IO 旁路）
    store = fragment_store or FragmentStore()

    # Consolidator：当 memory 暴露 ingest_structured 时早构造（lifespan 起调度器、手动整合
    # 都依赖它启动时已就位；懒构造会让 lifespan 读到 None、调度器永不注册）。无 llm 时
    # 退化为默认全保留去噪。
    _memory = getattr(agent, "memory", None)
    _llm = getattr(agent, "llm", None)
    consolidator: Consolidator | None = None
    if _memory is not None and hasattr(_memory, "ingest_structured"):
        tracker = ConsolidationTracker(
            path=store.fragments_dir.parent / "consolidation_status.json"
        )
        consolidator = Consolidator(
            fragment_store=store,
            memory=_memory,
            tracker=tracker,
            denoiser=LLMDenoiser(_llm) if _llm is not None else None,
        )
    app.state.fragment_store = store
    app.state.consolidator = consolidator

    # === 记忆路由（先注册；StaticFiles 兜底在最后） ===

    @app.post("/note", response_model=NoteResponse)
    def note(req: NoteRequest) -> NoteResponse:
        """记录一条消息到当天碎片文件（纯追加，零 LLM）。"""
        if not req.content.strip():
            raise HTTPException(status_code=422, detail="内容不能为空")
        d, t = store.append(req.content)
        return NoteResponse(ok=True, date=d, time=t)

    @app.get("/fragments", response_model=FragmentListResponse)
    def fragments_list() -> FragmentListResponse:
        """列出已有碎片文件（按日期倒排）。"""
        return FragmentListResponse(fragments=store.list_dates())

    @app.get("/fragments/{date_str}", response_model=FragmentContentResponse)
    def fragments_read(date_str: str) -> FragmentContentResponse:
        """读取指定日期的碎片内容（含 mtime，供 PUT 乐观锁）。"""
        content = store.read(date_str)
        if content is None:
            raise HTTPException(status_code=404, detail="该日期无碎片文件")
        return FragmentContentResponse(
            date=date_str, content=content, mtime=store.mtime(date_str)
        )

    @app.put("/fragments/{date_str}", response_model=FragmentPutResponse)
    def fragments_put(date_str: str, req: FragmentPutRequest) -> FragmentPutResponse:
        """整文件覆盖指定日期的碎片（供管理 UI 编辑）。

        带乐观锁：若 ``expected_mtime`` 与文件当前 mtime 不符，返回 409（防载入后被
        ``/note`` 追加致覆盖丢行）。未带 ``expected_mtime`` 则不校验（向后兼容）。
        """
        try:
            store.overwrite(date_str, req.content, expected_mtime=req.expected_mtime)
        except VersionMismatch:
            raise HTTPException(
                status_code=409, detail="碎片已被修改（版本冲突），请重新读取后再保存"
            )
        return FragmentPutResponse(ok=True, date=date_str)

    # --- 整合端点（需 memory / LLM，优雅 503） ---

    def _get_consolidator() -> Consolidator | None:
        """获取早构造的 Consolidator（无 memory/ingest_structured 时为 None → 路由 503）。"""
        return getattr(app.state, "consolidator", None)

    @app.post("/consolidate", response_model=ConsolidateResponse)
    def consolidate(req: ConsolidateRequest) -> ConsolidateResponse:
        """触发整合：无 date 默认整合昨天。整合今天须显式 date + 返回 warning。"""
        c = _get_consolidator()
        if c is None:
            raise HTTPException(status_code=503, detail="consolidation unavailable")

        target = req.date or (date.today() - timedelta(days=1)).isoformat()
        result = c.consolidate(target)

        warning = None
        if target == date.today().isoformat():
            warning = "今天整合后即锁定，今天后续消息不会自动入图"

        return ConsolidateResponse(
            ok=result.get("ok", True),
            date=result["date"],
            status=result["status"],
            events=result.get("events", 0),
            warning=warning,
        )

    @app.get("/consolidate/status")
    def consolidate_status(date_param: str = "") -> dict:
        """查询单日整合状态。"""
        c = _get_consolidator()
        if c is None:
            raise HTTPException(status_code=503, detail="consolidation unavailable")
        s = c._tracker.get(date_param or date.today().isoformat())
        return s.to_dict()

    @app.get("/consolidate/statuses")
    def consolidate_statuses() -> list[dict]:
        """查询全量整合状态（供管理看板日历）。"""
        c = _get_consolidator()
        if c is None:
            raise HTTPException(status_code=503, detail="consolidation unavailable")
        return [s.to_dict() for s in c._tracker.get_all()]

    # --- 日记端点（需 LLM，优雅 503） ---

    def _diary_store() -> DiaryStore:
        return DiaryStore(diaries_dir=store.fragments_dir.parent / "diaries")

    @app.post("/diary", response_model=DiaryGenerateResponse)
    def diary_generate(req: DiaryRequest) -> DiaryGenerateResponse:
        """生成/重生成日记：默认当天。"""
        llm = getattr(agent, "llm", None)
        if llm is None:
            raise HTTPException(status_code=503, detail="diary generation unavailable (no LLM)")

        target = req.date or date.today().isoformat()
        generator = DiaryGenerator(
            fragment_store=store, diary_store=_diary_store(), llm=llm,
        )
        try:
            result = generator.generate(target)
        except Exception:
            raise HTTPException(status_code=503, detail="diary generation failed")

        if result is None:
            return DiaryGenerateResponse(ok=False, date=target, reason="no_fragments")
        return DiaryGenerateResponse(ok=True, date=target)

    @app.get("/diary/{date_str}", response_model=DiaryContentResponse)
    def diary_read(date_str: str) -> DiaryContentResponse:
        """读取指定日期日记。"""
        content = _diary_store().read(date_str)
        if content is None:
            raise HTTPException(status_code=404, detail="该日期无日记")
        return DiaryContentResponse(date=date_str, content=content)

    @app.get("/diaries", response_model=DiaryListResponse)
    def diaries_list() -> DiaryListResponse:
        """列出已生成日记（按日期倒排）。"""
        return DiaryListResponse(diaries=_diary_store().list_dates())

    # --- 召回端点（只读 ReAct，禁 learn） ---

    @app.post("/recall", response_model=RecallResponse)
    def recall(req: RecallRequest) -> RecallResponse:
        """只读召回：用 readonly 元数据白名单的只读 agent 跑 ReAct，不写图。"""
        memory = getattr(agent, "memory", None)
        llm = getattr(agent, "llm", None)
        if memory is None or llm is None:
            raise HTTPException(status_code=503, detail="recall unavailable (no memory/LLM)")

        # readonly 白名单（非 "if != learn" 黑名单）：未来加写图工具标 readonly=False 即自动排除。
        readonly_config = ToolsetConfig(enabled=list(READONLY_TOOL_NAMES))
        # max_turns 可经 env 配（缺省 4）——召回是轻量查询、不需多轮
        recall_max_turns = int(os.environ.get("MCS_AGENT_RECALL_MAX_TURNS", "4"))
        readonly_agent = MemoryAgent(
            memory=memory, llm=llm, tools=readonly_config, max_turns=recall_max_turns,
        )
        return RecallResponse(reply=readonly_agent.chat(req.message))

    # === mcs_mem 前端（显式路由，在 StaticFiles mount 之前注册）===
    # manage.html 作主入口（``/``）；mcs_mem 自建图谱视图 /graph.html 由 StaticFiles 提供。
    mem_static = Path(__file__).parent / "static"
    manage_html = mem_static / "manage.html"
    if manage_html.is_file():

        @app.get("/")
        def index_page() -> Any:
            return FileResponse(str(manage_html))

        @app.get("/manage.html")
        def manage_page() -> Any:
            return FileResponse(str(manage_html))

    # === 基础路由（/chat /health /graph/expand，复用 mcs_agent） ===
    register_base_routes(app, agent)

    # === scheduler lifespan（随 app 起停） ===

    @asynccontextmanager
    async def _lifespan(app_instance: FastAPI):
        scheduler: ConsolidationScheduler | None = None
        c = getattr(app_instance.state, "consolidator", None)
        if c is not None:
            cron = os.environ.get("MCS_CONSOLIDATION_CRON", "30 0 * * *")
            enabled = os.environ.get("MCS_CONSOLIDATION_ENABLED", "true").lower() not in (
                "false", "0", "no",
            )
            scheduler = ConsolidationScheduler(consolidator=c, cron=cron, enabled=enabled)
            scheduler.start()
            app_instance.state.scheduler = scheduler
        yield
        if scheduler is not None:
            scheduler.shutdown()

    app.router.lifespan_context = _lifespan

    # === StaticFiles（最后挂载）===
    # mcs_mem/static 兜底：/graph.html（mcs_mem 自建图谱视图）等自己的前端页。
    # 不 mount mcs_agent/static——剥离 mcs_agent 前端（mcs_mem 有自己的 manage.html / graph.html）。
    if mem_static.is_dir():
        app.mount("/", StaticFiles(directory=str(mem_static), html=True), name="mem-static")
    # vendor（cytoscape 库）复用 mcs_agent/static/vendor——库非前端、共享可接受（mcs_mem 依赖 mcs_agent）。
    agent_vendor = Path(_mcs_agent_app.__file__).parent / "static" / "vendor"
    if agent_vendor.is_dir():
        app.mount("/vendor", StaticFiles(directory=str(agent_vendor)), name="vendor")

    return app


def run(host: str = "127.0.0.1", port: int = 8000) -> None:
    """构建 agent + 记忆应用并启动 uvicorn（记忆应用完整入口）。"""
    import uvicorn

    from mcs_agent.app import build_agent_from_env

    agent = build_agent_from_env()
    app = create_app(agent)
    uvicorn.run(app, host=host, port=port)

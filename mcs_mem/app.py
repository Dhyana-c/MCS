"""个人记忆应用（mcs_mem）——在 mcs_agent 基础路由之上扩展记忆功能。

依赖方向：``mcs_mem`` → ``mcs_agent`` → ``mcs``（单向）。

``create_app(agent, fragment_store=None)`` 自建 FastAPI app：
  1. 注册记忆路由（碎片 / 整合 / 日记 / 召回）+ ``/manage.html``；
  2. 复用 ``mcs_agent.register_base_routes``（``/chat`` / ``/health`` / ``/graph/expand``）；
  3. 设 scheduler lifespan（随 app 起停）；
  4. **最后** mount StaticFiles（``mcs_mem/static`` 兜底 ``graph.html`` 等）。

记忆路由 + ``/manage.html`` MUST 在 StaticFiles mount 之前注册——否则 ``/`` 兜底 mount
会拦截这些路径。``run`` 委托 ``mcs_agent.build_agent_from_env`` 构造 agent。

碎片为**结构化逐条对象** + **三态状态机**（pending / confirming / confirmed）：``/note``
创建 ``pending`` 碎片；``POST /fragments/{id}/confirm`` 确认即入图（一碎片一事件）；
``PUT`` / ``DELETE`` 仅作用于 ``pending``。捕获 / 状态标记是文件 IO 旁路（不碰 MCS）；
确认即 ingest 的协调（含并发 CAS）在 ``Consolidator``。
"""

from __future__ import annotations

import logging
import os
import re
from contextlib import asynccontextmanager
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Protocol

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from mcs_agent.app import register_base_routes
from mcs_agent.loop import MemoryAgent
from mcs_agent.tools import READONLY_TOOL_NAMES, ToolsetConfig

from mcs_mem.consolidation import ConsolidationTracker, Consolidator
from mcs_mem.diary import DiaryGenerator, DiaryStore
from mcs_mem.fragments import FragmentNotFound, FragmentStateError, FragmentStore
from mcs_mem.scheduler import ConsolidationScheduler

__all__ = ["create_app", "run"]

logger = logging.getLogger(__name__)


# === pydantic models（记忆端点契约） ===


class NoteRequest(BaseModel):
    content: str


class NoteResponse(BaseModel):
    ok: bool
    id: str
    date: str
    time: str


class FragmentListResponse(BaseModel):
    fragments: list[str]  # 有碎片的日期（倒排）


class FragmentItem(BaseModel):
    id: str
    time: str
    content: str
    status: str
    event_id: str | None = None


class FragmentsResponse(BaseModel):
    date: str
    fragments: list[FragmentItem]


class FragmentPutRequest(BaseModel):
    content: str


class FragmentMutateResponse(BaseModel):
    ok: bool
    id: str


class FragmentConfirmResponse(BaseModel):
    ok: bool
    id: str
    status: str
    event_id: str | None = None


class ConsolidateRequest(BaseModel):
    date: str | None = None


class ConsolidateResponse(BaseModel):
    ok: bool
    date: str
    confirmed: int
    skipped: int
    failed: int
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


# 日期入参形态校验（与 FragmentStore._validated_date 同口径）：date 直接拼文件路径
# （fragments/{date}.jsonl、diaries/{date}.md），不校验会被 ``../x`` 穿越出目录。
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _require_valid_date(date_str: str) -> str:
    """校验 ``YYYY-MM-DD`` 形态；非法抛 422（防路径拼接穿越）。"""
    if not _DATE_RE.match(date_str):
        raise HTTPException(status_code=422, detail="非法日期格式（需 YYYY-MM-DD）")
    return date_str


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

    # Consolidator：当 memory 暴露 ingest_structured 时早构造（lifespan 起调度器、手动确认
    # 都依赖它启动时已就位；懒构造会让 lifespan 读到 None、调度器永不注册）。
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
        )
    # recall 用只读 agent（readonly 白名单），构造一次复用——避免每请求重建 toolset / 重包 LLM。
    recall_agent: MemoryAgent | None = None
    if _memory is not None and _llm is not None:
        recall_agent = MemoryAgent(
            memory=_memory,
            llm=_llm,
            tools=ToolsetConfig(enabled=list(READONLY_TOOL_NAMES)),
            max_turns=int(os.environ.get("MCS_AGENT_RECALL_MAX_TURNS", "4")),
        )
    app.state.fragment_store = store
    app.state.consolidator = consolidator
    app.state.recall_agent = recall_agent

    # === 记忆路由（先注册；StaticFiles 兜底在最后） ===

    @app.post("/note", response_model=NoteResponse)
    def note(req: NoteRequest) -> NoteResponse:
        """记录一条消息：创建 pending 碎片（纯文件 IO，零 LLM / 零 MCS）。"""
        if not req.content.strip():
            raise HTTPException(status_code=422, detail="内容不能为空")
        frag_id, d, t = store.create(req.content)
        return NoteResponse(ok=True, id=frag_id, date=d, time=t)

    @app.get("/fragments", response_model=FragmentListResponse)
    def fragments_list() -> FragmentListResponse:
        """列出有碎片的日期（按日期倒排）。"""
        return FragmentListResponse(fragments=store.list_dates())

    @app.get("/fragments/{date_str}", response_model=FragmentsResponse)
    def fragments_read(date_str: str) -> FragmentsResponse:
        """读取指定日期的碎片列表（各态混列、带状态，按 time 排序）。"""
        if date_str not in store.list_dates():
            raise HTTPException(status_code=404, detail="该日期无碎片")
        items = [
            FragmentItem(
                id=f.id, time=f.time, content=f.content, status=f.status, event_id=f.event_id
            )
            for f in store.read_all(date_str)
        ]
        return FragmentsResponse(date=date_str, fragments=items)

    @app.put("/fragments/{frag_id}", response_model=FragmentMutateResponse)
    def fragments_put(frag_id: str, req: FragmentPutRequest) -> FragmentMutateResponse:
        """编辑单条碎片 content，**仅 pending**（confirming / confirmed → 409；不存在 → 404）。"""
        if not req.content.strip():
            raise HTTPException(status_code=422, detail="内容不能为空")
        try:
            store.update(frag_id, req.content)
        except FragmentNotFound:
            raise HTTPException(status_code=404, detail="碎片不存在")
        except FragmentStateError:
            raise HTTPException(status_code=409, detail="碎片非 pending，不可编辑")
        except ValueError:
            raise HTTPException(status_code=400, detail="非法碎片 id")
        return FragmentMutateResponse(ok=True, id=frag_id)

    @app.delete("/fragments/{frag_id}", response_model=FragmentMutateResponse)
    def fragments_delete(frag_id: str) -> FragmentMutateResponse:
        """删除单条碎片，**仅 pending**（confirming / confirmed → 409；不存在 → 404）。"""
        try:
            store.delete(frag_id)
        except FragmentNotFound:
            raise HTTPException(status_code=404, detail="碎片不存在")
        except FragmentStateError:
            raise HTTPException(status_code=409, detail="碎片非 pending，不可删除")
        except ValueError:
            raise HTTPException(status_code=400, detail="非法碎片 id")
        return FragmentMutateResponse(ok=True, id=frag_id)

    # --- 确认即入图（需 memory，优雅 503） ---

    def _get_consolidator() -> Consolidator | None:
        """获取早构造的 Consolidator（无 memory/ingest_structured 时为 None → 路由 503）。"""
        return getattr(app.state, "consolidator", None)

    @app.post("/fragments/{frag_id}/confirm", response_model=FragmentConfirmResponse)
    def fragment_confirm(frag_id: str) -> FragmentConfirmResponse:
        """确认单条碎片入图（confirm_one：CAS → ingest → mark）。"""
        c = _get_consolidator()
        if c is None:
            raise HTTPException(status_code=503, detail="consolidation unavailable")
        try:
            res = c.confirm_one(frag_id)
        except FragmentNotFound:
            raise HTTPException(status_code=404, detail="碎片不存在")
        except ValueError:
            raise HTTPException(status_code=400, detail="非法碎片 id")
        except Exception:
            raise HTTPException(status_code=500, detail="确认入图失败")
        return FragmentConfirmResponse(
            ok=res.get("ok", True),
            id=res["id"],
            status=res["status"],
            event_id=res.get("event_id"),
        )

    @app.post("/consolidate", response_model=ConsolidateResponse)
    def consolidate(req: ConsolidateRequest) -> ConsolidateResponse:
        """整合：确认指定日期剩余 pending 入图（无 date 默认确认昨天）。无 today warning。"""
        c = _get_consolidator()
        if c is None:
            raise HTTPException(status_code=503, detail="consolidation unavailable")

        target = (
            _require_valid_date(req.date)
            if req.date
            else (date.today() - timedelta(days=1)).isoformat()
        )
        result = c.consolidate(target)
        return ConsolidateResponse(
            ok=result.get("ok", True),
            date=result["date"],
            confirmed=result.get("confirmed", 0),
            skipped=result.get("skipped", 0),
            failed=result.get("failed", 0),
            warning=result.get("warning"),
        )

    @app.get("/consolidate/status")
    def consolidate_status(date_param: str = "") -> dict:
        """查询单日最后整合观测 ``{date, last_run, confirmed, failed}``。"""
        c = _get_consolidator()
        if c is None:
            raise HTTPException(status_code=503, detail="consolidation unavailable")
        return c.tracker.get(date_param or date.today().isoformat()).to_dict()

    @app.get("/consolidate/statuses")
    def consolidate_statuses() -> list[dict]:
        """全量观测（供管理看板日历）：每日 live ``pending`` / ``confirmed`` 计数 + 最后整合观测。"""
        c = _get_consolidator()
        if c is None:
            raise HTTPException(status_code=503, detail="consolidation unavailable")
        tracker = c.tracker
        dates = set(store.list_dates()) | {s.date for s in tracker.get_all()}
        out: list[dict] = []
        for d in sorted(dates, reverse=True):
            frags = store.read_all(d)
            pending = sum(1 for f in frags if f.status == "pending")
            confirmed = sum(1 for f in frags if f.status == "confirmed")
            obs = tracker.get(d)
            out.append(
                {
                    "date": d,
                    "pending": pending,
                    "confirmed": confirmed,
                    "last_run": obs.last_run,
                    "failed": obs.failed,
                }
            )
        return out

    # --- 日记端点（需 LLM，优雅 503） ---

    def _diary_store() -> DiaryStore:
        env_dir = os.environ.get("MCS_MEMORY_DIARIES_DIR")
        return DiaryStore(
            diaries_dir=Path(env_dir) if env_dir else store.fragments_dir.parent / "diaries"
        )

    @app.post("/diary", response_model=DiaryGenerateResponse)
    def diary_generate(req: DiaryRequest) -> DiaryGenerateResponse:
        """生成/重生成日记：默认当天。"""
        llm = getattr(agent, "llm", None)
        if llm is None:
            raise HTTPException(status_code=503, detail="diary generation unavailable (no LLM)")

        target = _require_valid_date(req.date) if req.date else date.today().isoformat()
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
        _require_valid_date(date_str)
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
        """只读召回：用 readonly 元数据白名单的只读 agent 跑 ReAct，不写图。

        agent 在 create_app 内构造一次复用（readonly 白名单 + max_turns 启动期读 env）。
        """
        ra = getattr(app.state, "recall_agent", None)
        if ra is None:
            raise HTTPException(status_code=503, detail="recall unavailable (no memory/LLM)")
        return RecallResponse(reply=ra.chat(req.message))

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
    # mcs_mem/static 兜底：/graph.html（自建图谱视图，含 vendor/cytoscape）等自己的前端页。
    # mcs_mem 是独立项目、自带前端（manage.html / graph.html / vendor），不 mount mcs_agent/static。
    if mem_static.is_dir():
        app.mount("/", StaticFiles(directory=str(mem_static), html=True), name="mem-static")

    return app


def run(host: str = "127.0.0.1", port: int = 8000) -> None:
    """构建 agent + 记忆应用并启动 uvicorn（记忆应用完整入口）。"""
    import uvicorn

    from mcs_agent.app import build_agent_from_env

    agent = build_agent_from_env()
    app = create_app(agent)
    uvicorn.run(app, host=host, port=port)

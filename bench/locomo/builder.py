"""LoCoMo 对话式 ingest 建图（双轨事件，D3/D4）。

每会话一次 ``mcs.ingest``，``work_id=sample_id`` 启用 ③b 作品叙事事件抽取——一次 ingest
产生两类事件，正好对应 LoCoMo 的两类时间：

| | 产生方式 | universe / 时间轴 | LoCoMo 对应 |
|---|---|---|---|
| **当下事件**（摄入行为） | 规则、不经 LLM | ``__reality__``，timestamp=会话时间 | "5 月 8 日这场对话发生了" |
| **谈话中的事件**（叙述发生） | ③b ``extract_work_events`` LLM 抽取 | 对话 universe，narr_timestamp=事发时间 | "Sarah 5 月 7 日去了互助会" |

temporal 题问的全是第二类（"When did Sarah go to the support group?"），由对话 universe
的叙事时间轴（``timeline`` 工具）回答。相对时间（"yesterday"）→ 绝对日期的解析依赖配套
change ``work-event-anchor-resolution``（T0，未落地前 temporal 如实反映缺口）。

每对话独立 SQLite db（``locomo_{sample_id}.db``，D4）；resume（db 已存在则跳过）。框架
ingest（非 agent 建图）——对话会话必须全量按时序入图，无写入取舍空间（D6）。
"""

from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

from mcs.entities.decisions import IngestInput
from mcs.entities.graph import CLASS_EVENT
from mcs.utils.timestamps import timestamp_sort_value

from bench.locomo.data import LoCoMoDoc, LoCoMoSession
from bench.multihop_rag.builder import _make_mcs

logger = logging.getLogger(__name__)

DEFAULT_DB_DIR = Path(__file__).resolve().parent / "outputs" / "graphs"
PILOT_SAMPLE_ID = "conv-26"  # 试点对话（194 题，~5M token 验证全链路）


def format_session_text(session: LoCoMoSession) -> str:
    """会话拼接为 ``[会话时间] 说话者: 文本`` 逐行格式（peer-to-peer）。

    带图轮次追加 `` [shared image: {caption}]``（caption 按 ``dia_id`` 从 V2 变体移植；
    死链轮无 caption 则只保留原文）。时间锚点 ``[...]`` 就在每行里，供 ③b LLM 抽叙事
    事件时解析相对时间（依赖配套 change ``work-event-anchor-resolution``）。
    """
    lines: list[str] = []
    for t in session.turns:
        line = f"[{session.display_time}] {t.speaker}: {t.text}"
        if t.caption:
            line += f" [shared image: {t.caption}]"
        lines.append(line)
    return "\n".join(lines)


def ingest_doc_sessions(mcs: Any, doc: LoCoMoDoc) -> list[int]:
    """对 ``doc`` 的每个会话按时序 ingest，返回每会话叙事事件数（``ctx.work_event_nodes``）。

    每会话一次 ``mcs.ingest(IngestInput(work_id=sample_id, timestamp=会话ISO),
    doc_id=, chunk_id=session_N, section_title=)``。

    - ``work_id`` 启用 ③b（谈话中的事件落对话 universe）。
    - ``chunk_id=session_N`` 供 source_tracking 记 session 级溯源（检索轨 Recall@k 用）。
    - ``timestamp`` 回填为会话时间（非 ingest now），使 ``__reality__`` 时间轴反映对话时序。
    """
    counts: list[int] = []
    for session in doc.sessions:
        text = format_session_text(session)
        ctx = mcs.ingest(
            IngestInput(
                content=text,
                timestamp=session.timestamp_iso,
                work_id=doc.sample_id,
            ),
            doc_id=doc.sample_id,
            chunk_id=session.chunk_id,
            section_title=doc.sample_id,
        )
        counts.append(len(getattr(ctx, "work_event_nodes", []) or []))
    # 增量 flush 已 per-ingest；save_full 兜底守门重组的边删除 / 重挂。
    save = getattr(getattr(mcs, "store", None), "save_full", None)
    if callable(save):
        save()
    return counts


def build_locomo_graph(
    doc: LoCoMoDoc,
    llm: str = "deepseek",
    db_dir: str | Path = DEFAULT_DB_DIR,
    *,
    token_budget: int = 8000,
    record_path: str | Path | None = None,
    rerank: bool = True,
    force: bool = False,
) -> dict:
    """为单个对话建图（每对话独立 db，断点续跑）。

    Args:
        doc: 对话（``sample_id`` 即 canonical universe id）。
        llm: LLM 后端名（``deepseek`` / ``claude`` / ``ollama``）。
        db_dir: db 输出目录；产出 ``locomo_{sample_id}.db`` + ``.llm_calls.jsonl``。
        force: True 强制重建（覆盖既有 db）。
    """
    db_dir = Path(db_dir)
    db_path = db_dir / f"locomo_{doc.sample_id}.db"
    if db_path.exists() and not force:
        logger.info("跳过（db 已存在）：%s", db_path)
        return {"sample_id": doc.sample_id, "skipped": True,
                "sessions": len(doc.sessions), "db": str(db_path)}

    db_dir.mkdir(parents=True, exist_ok=True)
    rec = (str(record_path) if record_path is not None
           else str(db_path.with_suffix(".llm_calls.jsonl")))
    mcs = _make_mcs(llm, str(db_path), token_budget=token_budget,
                    record_path=rec, rerank=rerank)
    t0 = time.time()
    counts = ingest_doc_sessions(mcs, doc)
    stats = {
        "sample_id": doc.sample_id, "skipped": False,
        "sessions": len(doc.sessions),
        "narrative_events_total": sum(counts),
        "wall_s": round(time.time() - t0, 1),
        "db": str(db_path),
    }
    logger.info("建图完成：%s", stats)
    return stats


def build_all_graphs(
    docs: list[LoCoMoDoc],
    llm: str = "deepseek",
    db_dir: str | Path = DEFAULT_DB_DIR,
    *,
    sample_ids: set[str] | None = None,
    **kwargs: Any,
) -> list[dict]:
    """批量建图。``sample_ids`` 非空时只建子集；试点对话 ``conv-26`` 排最前。"""
    if sample_ids:
        ordered = [d for d in docs if d.sample_id in sample_ids]
        ordered.sort(key=lambda d: (d.sample_id != PILOT_SAMPLE_ID, d.sample_id))
    else:
        ordered = list(docs)
    return [build_locomo_graph(d, llm, db_dir, **kwargs) for d in ordered]


def selfcheck_graph(mcs: Any, sample_id: str) -> dict:
    """建图后自检（D11 试点诊断）：双轨事件数 + 叙事时间戳可排序比例 + universe 归属。

    - ``narrative_events``：对话 universe 的事件数（③b 抽取，应 > 0）。
    - ``ingest_events``：``__reality__`` universe 的事件数（摄入行为，应 == 会话数）。
    - ``sortable_ratio``：叙事事件 ``narr_timestamp`` 可排序占比（ISO / 数字年）；
      依赖配套 change ``work-event-anchor-resolution``（T0）——未落地前相对时间
      （"yesterday"）垫底不可排，此 ratio 如实反映缺口。**注意误报盲区**：
      ``"8 May, 2023"`` 这类非 ISO 会被数字年解析取首整数 8 当"年"——判"可排"但
      排序错乱，故同时返回 ``timestamp_samples`` 供人工核对实际形态。
    - ``universe_ok``：叙事事件全在对话 universe（未被错挂 ``__reality__``）。
    """
    events = list(mcs.store.get_nodes_by_class(CLASS_EVENT))
    narrative = [n for n in events if n.universe == sample_id]
    ingest = [n for n in events if n.universe == "__reality__"]
    sortable = 0
    samples: list[str] = []
    for ev in narrative:
        meta = (ev.extensions or {}).get("event_meta", {})
        ts = meta.get("timestamp", "") if isinstance(meta, dict) else ""
        if timestamp_sort_value(ts) != float("-inf"):
            sortable += 1
        if len(samples) < 5:
            samples.append(str(ts))
    return {
        "sample_id": sample_id,
        "narrative_events": len(narrative),
        "ingest_events": len(ingest),
        "sortable_ratio": round(sortable / len(narrative), 3) if narrative else 0.0,
        "timestamp_samples": samples,
        "universe_ok": all(n.universe == sample_id for n in narrative),
    }
